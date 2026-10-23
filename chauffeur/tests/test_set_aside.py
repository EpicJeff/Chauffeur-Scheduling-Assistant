"""A run's minutes are the time SET ASIDE for each session; the library program's minutes are
the LESSON LENGTH every script is written against (library_scripts budgets on made_for.minutes).

Pinned here (user ruling 2026-10-23): a library run never sets aside less than its lesson runs
(POST /api/programs, /edit, preview-slots, Argyle's "use it" path all floor at made_for.minutes);
the run view names the lesson length; a logged session defaults to the lesson length, not the
block; a lesson-length change on the library outdates every generated script (budget recorded,
Write lessons picks them up, nothing is scheduled by itself) and flags hand edits stale; the
sheets say "Set aside" with the lesson length beside it.

Run from chauffeur/:  python tests/test_set_aside.py   (HA_BASE_URL unset)
"""
import copy
import re
from unittest.mock import patch

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)
from fastapi.testclient import TestClient
from services import storage, programs, library, library_scripts, programs_curate, program_lessons as pl

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
AUNT = {'id': 'aunt', 'name': 'Aunt', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}
CURATED = {'phases': [{'name': 'Foundations', 'weeks': 2, 'steps': ['a'], 'milestone': 'm',
                       'units': [{'title': 'Middle C', 'sessions': 1, 'body': 'Find C. Play it with thumb 1.'},
                                 {'title': 'Five fingers', 'sessions': 1, 'body': 'C D E F G up and down.'}]}],
           'source': {'origin': 'generated', 'reason': 'test'}}
SAY = [{'type': 'say', 'text': 'Sit at the keys, {name}.'}]
LONG = {'scenes': [{'type': 'teach', 'title': 'Middle C', 'text': 'C sits left of the two black keys. ' * 4,
                    'examples': [{'text': 'Play C, rest, C'}], 'speak': 'Find the two black keys and step left.'}]
                  + [{'type': 'do', 'text': 'Play C and D', 'seconds': 600}] * 3}
WRITE_CALLS = []
LESSON_MINUTES = 20
SLOT_MON = {'day': 0, 'time_start': '18:00'}
SLOT_WED = {'day': 2, 'time_start': '18:00'}


def _write(library_id, actor, *a, **k):
    WRITE_CALLS.append(library_id)
    return {'status': 'ok', 'job': None}


def _reset():
    import main
    WRITE_CALLS.clear()
    main.trigger_background_refresh = lambda *a, **k: None
    library_scripts.write = _write
    programs_curate.curate = lambda *a, **k: copy.deepcopy(CURATED)
    for t in ('programs', 'library_programs', 'library_scripts', 'members', 'projects', 'protected_commitments'):
        getattr(storage, t + '_table').truncate()
    storage.set_app_state(library_scripts.JOBS_KEY, {})
    for m in (MOM, AUNT, KID):
        storage.add_member(dict(m))
    from services import projects
    p = projects.create({'title': 'Piano for Kate', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'kid',
                         'audience': 'household'}, dict(MOM))['project']
    lib = storage.add_library_program(library.from_curated(
        'Learn piano', {'age_band': 'any', 'minutes': LESSON_MINUTES, 'sessions_per_week': 2, 'assumes': ''},
        copy.deepcopy(CURATED), 'mom'))
    return p['id'], lib


def _c():
    import main
    return TestClient(main.app)


def _h(who):
    return {'X-Member-Token': storage.create_member_token(who)}


def _start(pid, lib, who='mom', **extra):
    body = {'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, **extra}
    r = _c().post('/api/programs', headers=_h(who), json=body)
    check(r.status_code == 200 and r.json().get('status') == 'success', f'a run from the library: {r.text[:300]}')
    return r.json()


def _profile(minutes, **extra):
    return {'made_for': {'age_band': 'any', 'minutes': minutes, 'sessions_per_week': 2, 'assumes': '', **extra}}


def _legacy_run():
    return storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'state': 'active', 'created_by': 'mom', 'sessions': [],
                                'shape': {'minutes': 30, 'sessions_per_week': 2, 'preferred_days': []},
                                'phases': [{'name': 'Chords', 'weeks': 4, 'milestone_hit_at': None}], 'source': {}})


def _slot(lib, index, label=''):
    lesson = storage.get_library_program(lib)['lessons'][index]
    return lesson, {'lesson_id': lesson['id'], 'variant_label': label}


def _generated(lib, index, minutes=1, **extra):
    """A model-written script in storage, the way the writer leaves one (claimed, then committed)."""
    lesson, slot = _slot(lib, index)
    token = storage.claim_library_script(lib, slot)
    check(bool(token), 'the slot is claimable')
    data = {'origin': 'generated', 'source_url': '', 'scenes': SAY, 'model': 'test', 'attempts': 0, 'note': '',
            'minutes': minutes, **extra}
    check(bool(storage.commit_library_script(lib, slot, token, data)), 'the script is committed')
    return lesson, slot


def _view(lib, lesson, label=''):
    return (library.get(lib, dict(MOM))['scripts'].get(lesson['id']) or {}).get(label) or {}


# --- the floor: a run never sets aside less than its lesson runs -------------------------------

def scenario_a_run_from_the_library_sets_aside_at_least_the_lesson_length():
    pid, lib = _reset()
    made = _start(pid, lib, minutes=15)
    run = storage.get_program(made['id'])
    check(run['shape']['minutes'] == LESSON_MINUTES, f'15 asked for a 20-minute lesson sets aside 20: {run["shape"]}')
    check(made['program'].get('lesson_minutes') == LESSON_MINUTES,
          f'the answer names the lesson length: {made["program"].get("lesson_minutes")}')
    made = _start(pid, lib, minutes=30)
    check(storage.get_program(made['id'])['shape']['minutes'] == 30, "more than the lesson is the person's to set aside")
    made = _start(pid, lib)
    check(storage.get_program(made['id'])['shape']['minutes'] == LESSON_MINUTES, 'nothing said = the lesson length')
    check(storage.get_library_program(lib)['made_for']['minutes'] == LESSON_MINUTES, 'the library never moves for a run')


def scenario_edit_floors_a_proposal_and_a_run_under_way():
    pid, lib = _reset()
    rid = _start(pid, lib, minutes=30)['id']
    r = _c().post(f'/api/programs/{rid}/edit', headers=_h('mom'), json={'minutes': 10})
    check(r.status_code == 200 and r.json()['status'] == 'success'
          and storage.get_program(rid)['shape']['minutes'] == LESSON_MINUTES,
          f'a proposal edited below the lesson lands on the lesson length: {r.text[:200]} {storage.get_program(rid)["shape"]}')
    r = _c().post(f'/api/programs/{rid}/edit', headers=_h('mom'), json={'minutes': 45})
    check(storage.get_program(rid)['shape']['minutes'] == 45, 'above the lesson is kept')
    rid = _start(pid, lib, minutes=30, activate=True, slots=[SLOT_MON, SLOT_WED])['id']
    check(storage.get_program(rid)['state'] == 'active', 'a parent activates')
    r = _c().post(f'/api/programs/{rid}/edit', headers=_h('mom'), json={'minutes': 5})
    row = storage.get_program(rid)
    check(r.json()['status'] == 'success' and row['shape']['minutes'] == LESSON_MINUTES,
          f'a run under way floors too: {r.text[:200]} {row["shape"]}')
    check(all(s['time_end'] == '18:20' for s in row['shape']['slots']), f'its windows run the lesson length: {row["shape"]["slots"]}')
    ends = {storage.get_protected_commitment(c)['time_end'] for c in row['emissions']['commitment_ids']}
    check(ends == {'18:20'}, f'and so does the calendar: {ends}')


def scenario_preview_slots_floor_only_when_a_library_program_is_named():
    pid, lib = _reset()
    r = _c().post('/api/programs/preview-slots', headers=_h('mom'), json={'member_id': 'kid', 'library_id': lib, 'minutes': 15})
    check(r.status_code == 200 and r.json()['minutes'] == LESSON_MINUTES, f'the preview shows what the run will set aside: {r.text}')
    r = _c().post('/api/programs/preview-slots', headers=_h('mom'), json={'member_id': 'kid', 'library_id': lib, 'minutes': 25})
    check(r.json()['minutes'] == 25, 'above the lesson passes')
    r = _c().post('/api/programs/preview-slots', headers=_h('mom'), json={'member_id': 'kid', 'minutes': 15, 'sessions_per_week': 2})
    check(r.json()['minutes'] == 15, "a new program's minutes ARE its lesson length; no floor without a library row")


def scenario_argyle_use_path_floors_too():
    from services import agent_tools_v2
    pid, lib = _reset()
    choice = {'title': 'Learn piano', 'member_id': 'kid', 'starting_point': '', 'project_id': pid, 'created_by': 'mom',
              'library_id': lib, 'shape': programs.clamp_shape({'minutes': 15, 'sessions_per_week': 2, 'preferred_days': []})}
    res = agent_tools_v2._start_program_choice(choice, dict(MOM))
    check(res.get('status') == 'success', f'Argyle starts the run: {res}')
    shape = storage.get_program(res['run_id'])['shape']
    check(shape['minutes'] == LESSON_MINUTES, f'the chat door floors like the sheet: {shape}')


def scenario_the_run_view_names_the_lesson_length():
    pid, lib = _reset()
    rid = _start(pid, lib, minutes=30)['id']
    loaded = programs.load(storage.get_program(rid))
    check(loaded.get('lesson_minutes') == LESSON_MINUTES and loaded['shape']['minutes'] == 30,
          f'set aside 30, lesson 20, both on the view: {loaded.get("lesson_minutes")} {loaded["shape"]}')
    r = _c().get('/api/programs?include_finished=true', headers=_h('mom'))
    row = next(p for p in r.json()['programs'] if p['id'] == rid)
    check(row.get('lesson_minutes') == LESSON_MINUTES, f'the list the sheets read carries it: {row.get("lesson_minutes")}')
    check(programs.load(storage.get_program(_legacy_run())).get('lesson_minutes') is None,
          'a legacy run has no lesson length to name')


def scenario_a_logged_session_defaults_to_the_lesson_length():
    pid, lib = _reset()
    rid = _start(pid, lib, minutes=30, activate=True, slots=[SLOT_MON])['id']
    check(programs.log_session(rid)['status'] == 'success', 'logged')
    check(programs.log_session(rid, minutes=12)['status'] == 'success', 'logged with a said length')
    minutes = [s['minutes'] for s in storage.get_program(rid)['sessions']]
    check(minutes == [LESSON_MINUTES, 12], f'the block is 30 but the lesson is 20; a said length is kept: {minutes}')
    legacy = _legacy_run()
    programs.log_session(legacy)
    check([s['minutes'] for s in storage.get_program(legacy)['sessions']] == [30], 'a legacy run only has its own minutes')


# --- the wrinkle: a lesson-length change outdates the scripts written for the old one ---------

def scenario_a_lesson_length_change_outdates_generated_scripts_and_flags_hand_edits():
    pid, lib = _reset()
    gen_lesson, gen_slot = _generated(lib, 0)
    hand_lesson, hand_slot = _slot(lib, 1)
    check(bool(storage.edit_library_script(lib, hand_slot, {'origin': 'generated', 'scenes': SAY, 'minutes': 1})), 'a hand edit stored')
    check(not library_scripts.needs_script(lib, gen_slot) and not library_scripts.needs_script(lib, hand_slot), 'both complete before')
    check(not _view(lib, gen_lesson).get('outdated') and not _view(lib, hand_lesson).get('stale'), 'nothing flagged before')

    res = library.update(lib, _profile(30), dict(MOM))
    check(res.get('status') == 'success' and res['program']['made_for']['minutes'] == 30, f'the lesson length changed: {res}')

    gen = storage.get_library_script(lib, gen_slot)
    check(gen.get('scenes') == SAY and not gen.get('edited'), 'the old script stays in place and still plays')
    check(int(gen.get('budget') or 0) == LESSON_MINUTES, f'it records the length it was written for: {gen.get("budget")}')
    check(library_scripts.needs_script(lib, gen_slot), 'Write lessons picks it up')
    view = _view(lib, gen_lesson)
    check(view.get('state') == 'ready' and view.get('outdated') is True and view.get('budget') == LESSON_MINUTES,
          f'the course says written for 20: {view}')
    hand = storage.get_library_script(lib, hand_slot)
    check(hand.get('edited') and hand.get('stale') is True, f'a hand edit is flagged, never rewritten: {hand}')
    check(not library_scripts.needs_script(lib, hand_slot), 'the job leaves hand edits alone')
    check(not _view(lib, hand_lesson).get('outdated') and _view(lib, hand_lesson).get('stale'),
          'a hand edit shows the stale chip, not the outdated one')
    check(WRITE_CALLS == [], 'nothing is written by itself; the person taps Write lessons')

    res = library.update(lib, _profile(LESSON_MINUTES), dict(MOM))
    check(res.get('status') == 'success' and not library_scripts.needs_script(lib, gen_slot)
          and not _view(lib, gen_lesson).get('outdated'), 'back to 20 and the 20-minute script is current again')
    res = library.update(lib, _profile(30), dict(MOM))
    check(res.get('status') == 'success' and library_scripts.needs_script(lib, gen_slot), 'and outdated once more at 30')

    other = library.update(lib, _profile(30, age_band='explorer', sessions_per_week=3, assumes='knows C'), dict(MOM))
    check(other.get('status') == 'success' and storage.get_library_script(lib, gen_slot).get('budget') == LESSON_MINUTES
          and storage.get_library_script(lib, hand_slot).get('stale') is True,
          'a profile change that leaves the minutes alone touches no script flag (the ruling stands)')


def scenario_a_fresh_write_records_the_new_length_and_a_later_hand_edit_wins():
    from services import model_pools
    pid, lib = _reset()
    gen_lesson, gen_slot = _generated(lib, 0)
    library.update(lib, _profile(30), dict(MOM))
    check(library_scripts.needs_script(lib, gen_slot), 'outdated')
    with patch.object(model_pools, 'call_pool_json', lambda *a, **k: copy.deepcopy(LONG)):
        row = library_scripts.generate_script(storage.get_library_program(lib), gen_lesson, '', {'llm_gemini_api_key': 'k'})
    check(row and row['scenes'][0]['type'] == 'teach' and int(row.get('budget') or 0) == 30,
          f'the rewrite records the 30 it was written for: {row and (row.get("budget"), row["scenes"][0]["type"])}')
    check(not library_scripts.needs_script(lib, gen_slot) and not _view(lib, gen_lesson).get('outdated'), 'current again')

    library.update(lib, _profile(45), dict(MOM))
    check(library_scripts.needs_script(lib, gen_slot), 'outdated at 45')
    check(bool(storage.edit_library_script(lib, gen_slot, {'origin': 'generated', 'scenes': SAY, 'minutes': 1})), 'then edited by hand')
    check(not library_scripts.needs_script(lib, gen_slot) and not _view(lib, gen_lesson).get('outdated'),
          'a hand edit is never overwritten by the job, outdated or not')


def scenario_a_runs_set_aside_is_never_moved_by_the_library():
    pid, lib = _reset()
    rid = _start(pid, lib, activate=True, slots=[SLOT_MON])['id']
    library.update(lib, _profile(30), dict(MOM))
    row = storage.get_program(rid)
    check(row['shape']['minutes'] == LESSON_MINUTES and all(s['time_end'] == '18:20' for s in row['shape']['slots']),
          f"the calendar block is a person's act; the library never widens it: {row['shape']}")
    loaded = programs.load(row)
    check(loaded['lesson_minutes'] == 30 and loaded['shape']['minutes'] == 20, 'the view shows the gap for the sheet to say')


# --- the words on the sheets -------------------------------------------------------------------

def _src(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def scenario_the_sheets_say_set_aside_and_name_the_lesson_length():
    sheet = _src('templates/components/program_setup_sheet.html')
    page = _src('templates/components/programs_page.html')
    card = _src('templates/components/library_card.html')
    check('Minutes each' not in sheet and 'Minutes each' not in page, 'the run never asks "Minutes each" any more')
    check(re.search(r'Set aside', sheet) and re.search(r'Set aside', page), 'both run sheets ask what to set aside')
    check('data-setup-minutes' in sheet and re.search(r'data-setup-minutes[^>]*:min=', sheet), 'the setup input floors at the lesson length')
    check('data-lesson-length' in sheet and 'data-lesson-length' in page, 'the lesson length is said beside the set-aside input')
    check('lesson_minutes' in sheet and 'lesson_minutes' in page, 'from the run view / library row, never a constant')
    check('data-set-aside-short' in page, 'a run whose lesson grew past its block says so on the programs page')
    check(re.search(r'name="minutes"[^>]*:min=', page), 'Program settings floors too')
    check('Lesson length' in card, 'the library card calls its minutes the lesson length')
    check('data-script-outdated' in _src('templates/components/library_page.html'), 'the course shows a written-for-N chip with Rewrite')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
