"""Program-owned lesson scripts (spec 2026-10-20-lesson-depth-design.md rev 3, sections 1, 2, 6, 7).

Pinned here: the five storage doors and their claim tokens; the job and its ownership; the
nightly retry; the migration; the run routes reading through one resolver with variables
filled; the library script routes and who may use them.

Run from chauffeur/:  python tests/test_library_scripts.py   (HA_BASE_URL unset)
"""
import threading
import time
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)
from program_fixture import add_run
from services import storage, program_lessons as pl

PIANO = {'title': 'Learn piano', 'shape': {'minutes': 30, 'sessions_per_week': 3},
         'phases': [{'name': 'Foundations', 'what': 'Hands and keys', 'milestone': 'A scale',
                     'units': [{'n': 1, 'title': 'Middle C', 'sessions': 1, 'body': 'Find C. Play it with thumb 1.'},
                               {'n': 2, 'title': 'Five fingers', 'sessions': 1, 'body': 'C D E F G up and down.'}],
                     'rotation': [{'label': 'Session A', 'steps': ['Right hand']},
                                  {'label': 'Session B', 'steps': ['Left hand']}]}],
         'source': {'origin': 'generated', 'reason': 'test'}}
SAY = [{'type': 'say', 'text': 'Sit at the keys, {name}.'}]
TEACH = [{'type': 'teach', 'title': 'Middle C', 'text': 'C sits left of the two black keys. ' * 4,
          'examples': [{'text': 'Play C, rest, C'}, {'text': 'Dó', 'speak_lang': 'pt-BR'}],
          'speak': 'Find the two black keys and step left.'}]


def _reset():
    for t in ('programs', 'library_programs', 'program_lessons', 'library_scripts', 'members', 'projects'):
        getattr(storage, t + '_table').truncate()
    storage.set_app_state(pl_jobs_key(), {})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult'})
    storage.add_member({'id': 'kate', 'name': "D'Arcy Zoë", 'role': 'child'})
    storage.add_member({'id': 'sam', 'name': 'Sam', 'role': 'child'})
    storage.add_project({'id': 'prj', 'title': 'Piano for Kate', 'goal': 'piano', 'done_when': 'habit',
                         'owner_member_id': 'mom', 'created_by': 'mom', 'audience': 'household', 'pieces': [], 'steps': []})
    rid = add_run({'member_id': 'kate', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **PIANO})
    run = storage.get_program(rid)
    lid = run['library_id']
    lesson = storage.get_library_program(lid)['lessons'][0]
    return rid, lid, lesson


def pl_jobs_key():
    from services import library_scripts
    return library_scripts.JOBS_KEY


def _slot(lesson, label='Session A'):
    return {'lesson_id': lesson['id'], 'variant_label': label}


def _data(scenes=SAY, **kw):
    return {'origin': 'generated', 'source_url': '', 'scenes': scenes, 'model': 'test',
            'attempts': 0, 'note': '', 'minutes': 1, **kw}


# --- doors -------------------------------------------------------------------

def scenario_claim_then_commit_then_nobody_else():
    rid, lid, lesson = _reset()
    t1 = storage.claim_library_script(lid, _slot(lesson))
    check(t1, 'an empty slot can be claimed')
    t2 = storage.claim_library_script(lid, _slot(lesson))
    check(t2 and t2 != t1, 'a second claim on a still-empty slot refreshes the token')
    check(storage.commit_library_script(lid, _slot(lesson), t1, _data()) == '', 'the stale first token is refused')
    new = storage.commit_library_script(lid, _slot(lesson), t2, _data())
    check(new, 'the current token commits')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row['scenes'] == SAY and row['claim'] == new, f'row stored with the new token, got {row}')
    check(storage.claim_library_script(lid, _slot(lesson)) is None, 'a slot with scenes cannot be claimed')
    check(storage.commit_library_script(lid, _slot(lesson), new, _data(scenes=[], attempts=1, note='x')) == '',
          'a failure record never lands on scenes')


def scenario_failure_record_lands_only_on_an_empty_slot():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    check(storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=[], attempts=1, note='pool empty')),
          'a failure commits onto its own claim')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row['attempts'] == 1 and row['note'] == 'pool empty' and not row['scenes'], f'failure row, got {row}')
    check(storage.claim_library_script(lid, _slot(lesson)), 'a failure row is still claimable')


def scenario_commit_after_library_delete_archive_or_lesson_removal_is_dropped():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.update_library_program(lid, {'archived': True})
    check(storage.commit_library_script(lid, _slot(lesson), t, _data()) == '', 'archived: dropped')
    storage.update_library_program(lid, {'archived': False})
    t = storage.claim_library_script(lid, _slot(lesson))
    row = storage.get_library_program(lid)
    storage.update_library_program(lid, {'lessons': [l for l in row['lessons'] if l['id'] != lesson['id']]})
    check(storage.commit_library_script(lid, _slot(lesson), t, _data()) == '', 'lesson gone: dropped')
    storage.update_library_program(lid, {'lessons': row['lessons']})
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.delete_library_program(lid)
    check(storage.commit_library_script(lid, _slot(lesson), t, _data()) == '', 'library gone: dropped')
    check(storage.get_library_scripts(lid) == [], 'library delete removed its script rows')


def scenario_replace_is_in_place_and_conditional():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    t2 = storage.commit_library_script(lid, _slot(lesson), t, _data())
    longer = SAY + [{'type': 'do', 'text': 'Play C ten times', 'seconds': 60}]
    before = storage.get_library_script(lid, _slot(lesson))['id']
    seen = []
    orig_remove = storage.library_scripts_table.remove

    def spy(*a, **kw):
        seen.append('remove')
        return orig_remove(*a, **kw)
    with patch.object(storage.library_scripts_table, 'remove', spy):
        t3 = storage.replace_library_script(lid, _slot(lesson), t2, _data(scenes=longer, minutes=2))
    check(t3 and storage.get_library_script(lid, _slot(lesson))['scenes'] == longer, 'replace landed')
    check(storage.replace_library_script(lid, _slot(lesson), t2, _data()) == '', 'the old token is refused')
    ids = [r['id'] for r in storage.get_library_scripts(lid)]
    check(len(ids) == 1, f'one row, never an empty window, got {ids}')
    check(not seen, f'replace never removes the row first, got {seen}')
    check(ids == [before], f'the same row, replaced in place, got {ids} for {before}')


def scenario_an_edit_during_a_job_wins():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.edit_library_script(lid, _slot(lesson), _data(scenes=[{'type': 'say', 'text': 'Mine'}]))
    check(storage.commit_library_script(lid, _slot(lesson), t, _data()) == '', 'the in-flight generated result is dropped')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row['edited'] and row['scenes'][0]['text'] == 'Mine', f'the edit stands, got {row}')
    check(storage.replace_library_script(lid, _slot(lesson), row['claim'], _data()) == '', 'replace never touches an edit')
    check(storage.edit_library_script(lid, _slot(lesson), _data(scenes=[{'type': 'say', 'text': 'Again'}])),
          'an edit replaces an edit')


def scenario_delete_invalidates_every_token():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    t2 = storage.commit_library_script(lid, _slot(lesson), t, _data())
    check(storage.delete_library_script(lid, _slot(lesson)), 'deleted')
    check(storage.replace_library_script(lid, _slot(lesson), t2, _data()) == '', 'old token dead after delete')
    t3 = storage.claim_library_script(lid, _slot(lesson))
    check(storage.commit_library_script(lid, _slot(lesson), t3, _data()), 'a fresh claim commits')


# --- generation ----------------------------------------------------------------

def _fake_pool(answers):
    """Each call pops the next answer; records the tier and prompts."""
    calls = []

    def call(tier, key, system, prompt, **kw):
        calls.append({'tier': tier, 'system': system, 'prompt': prompt})
        return answers.pop(0) if answers else {'error': 'empty'}
    return call, calls


def _short():
    return {'scenes': SAY}


def _long():
    return {'scenes': TEACH + [{'type': 'do', 'text': 'Play C and D', 'seconds': 600}] * 3}


def scenario_a_short_script_is_stored_then_retried_once_and_replaced():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    call, calls = _fake_pool([_short(), _long()])
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'})
    check(len(calls) == 2, f'one retry, got {len(calls)}')
    check('runs about' in calls[1]['prompt'] and 'of the 30 asked' in calls[1]['prompt'], f'shortfall named: {calls[1]["prompt"][-200:]}')
    check(row and row['scenes'][0]['type'] == 'teach', 'the longer result replaced the first')
    check(row['minutes'] >= 15 and not row['note'], f'estimate honest, no note, got {row["minutes"]} {row["note"]!r}')


def scenario_retry_needs_allowance_and_a_worse_second_changes_nothing():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    call, calls = _fake_pool([_short(), _long()])
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'}, allowance=1)
    check(len(calls) == 1 and row['scenes'] == pl.sanitize_script(SAY, 'generated', minutes=30), 'no allowance: first kept')
    check(row['note'] == 'runs about 0 minutes of 30' or row['note'].startswith('runs about'), f'note set, got {row["note"]!r}')
    storage.delete_library_script(lid, _slot(lesson))
    call, calls = _fake_pool([_short(), {'error': 'boom', 'transient': True}])
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'})
    check(len(calls) == 2 and row['scenes'][0]['type'] == 'say' and row['attempts'] == 0,
          'a failed retry keeps the first script and records no attempt')


def scenario_a_full_length_script_costs_one_call_and_resets_attempts():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=[], attempts=2, note='old'))
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'})
    check(len(calls) == 1 and row['attempts'] == 0 and not row['note'], f'one call, attempts reset, got {row}')


def scenario_the_pool_setting_picks_the_tier():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    for setting, tier in ((None, 'heavy'), ('background', 'background'), ('heavy', 'heavy'), ('bogus', 'heavy')):
        storage.delete_library_script(lid, _slot(lesson))
        settings = {'llm_gemini_api_key': 'k', **({'lesson_pool': setting} if setting else {})}
        call, calls = _fake_pool([_long()])
        with patch.object(model_pools, 'call_pool_json', call):
            library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A', settings)
        check(calls[0]['tier'] == tier, f'{setting!r} -> {tier}, got {calls[0]["tier"]}')


def scenario_the_prompt_carries_the_spine():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    row = storage.get_library_program(lid)
    second = row['lessons'][1]
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call):
        library_scripts.generate_script(row, second, 'Session B', {'llm_gemini_api_key': 'k'})
    p = calls[0]['prompt']
    for needle in ('Hands and keys', 'Middle C', 'Find C. Play it with thumb 1.', '30 minutes', 'between 24 and 36',
                   'Up to 30 scenes', '{name}', 'complete beginner' if row['made_for'].get('assumes') else 'all ages'):
        check(needle in p, f'prompt lacks {needle!r}: {p[:600]}')
    check('Five fingers' in p, 'this lesson named')
    s = calls[0]['system']
    for needle in ('Open', 'Teach', 'Work', 'Wrap', '"type":"teach"', 'movement', 'cooking', 'phonics', 'problem-shaped',
                   'language', 'music', '{name}', '{project}', 'Nothing else goes in braces'):
        check(needle in s, f'system prompt lacks {needle!r}')
    check('At most 10 scenes' not in s, 'the old cap line is gone')


def scenario_a_cited_lesson_still_needs_its_page():
    from services import library_scripts, model_pools, web
    rid, lid, lesson = _reset()
    row = storage.get_library_program(lid)
    storage.update_library_program(lid, {'source': {**row['source'], 'origin': 'cited'},
                                         'lessons': [{**row['lessons'][0], 'url': 'https://example.test/c'}] + row['lessons'][1:]})
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call), patch.object(web, 'read_page', lambda u: ''):
        out = library_scripts.generate_script(storage.get_library_program(lid), storage.get_library_program(lid)['lessons'][0],
                                              'Session A', {'llm_gemini_api_key': 'k'})
    check(out is None and not calls, 'an unreadable page spends nothing and stores nothing')


# --- the job ---------------------------------------------------------------------

def _wait(pred, s=5.0):
    end = time.time() + s
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def scenario_write_runs_every_lesson_in_order_and_clears():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    mom = storage.get_member('mom')
    fake, calls = _fake_pool([_long()] * 4)
    gate = threading.Event()

    def call(*a, **kw):
        gate.wait(5)
        return fake(*a, **kw)
    with patch.object(model_pools, 'call_pool_json', call):
        res = library_scripts.write(lid, mom)
        check(res['status'] == 'ok' and res['job']['total'] == 4, f'four (lesson, variant) pairs, got {res}')
        check(library_scripts.write(lid, mom)['message'] == 'Already writing lessons for this program.', 'second refused')
        gate.set()
        check(_wait(lambda: library_scripts.job_state(lid) is None), 'entry cleared at the end')
    rows = storage.get_library_scripts(lid)
    check(len(rows) == 4 and all(r['scenes'] for r in rows), f'four scripts, got {len(rows)}')
    order = [p['prompt'] for p in calls]
    # Each prompt names the next and the previous lesson's titles, so titles cannot tell the order
    # apart; the second lesson's own body appears only in its own prompts.
    second_body = 'C D E F G up and down.'
    check([second_body in p for p in order] == [False, False, True, True], 'ladder order: Middle C first, then Five fingers')


def scenario_regenerate_one_deletes_then_claims_and_writes_that_one():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data())
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call):
        res = library_scripts.write(lid, storage.get_member('mom'), lesson_id=lesson['id'], variant_label='Session A')
        check(res['status'] == 'ok' and res['job']['total'] == 1, f'one lesson, got {res}')
        check(_wait(lambda: library_scripts.job_state(lid) is None), 'cleared')
    check(len(calls) == 1 and storage.get_library_script(lid, _slot(lesson))['scenes'][0]['type'] == 'teach', 'rewritten')
    check(len(storage.get_library_scripts(lid)) == 1, 'the other slots untouched')


def scenario_job_result_after_edit_is_dropped():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    gate = threading.Event()

    def call(tier, key, system, prompt, **kw):
        gate.wait(5)
        return _long()
    with patch.object(model_pools, 'call_pool_json', call):
        library_scripts.write(lid, storage.get_member('mom'), lesson_id=lesson['id'], variant_label='Session A')
        check(_wait(lambda: storage.get_library_script(lid, _slot(lesson)) is not None), 'claimed')
        storage.edit_library_script(lid, _slot(lesson), _data(scenes=[{'type': 'say', 'text': 'Mine'}]))
        gate.set()
        check(_wait(lambda: library_scripts.job_state(lid) is None), 'job ended')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row['edited'] and row['scenes'][0]['text'] == 'Mine', f'edit stands, got {row}')


def scenario_delete_mid_call_leaves_nothing():
    from services import library_scripts, model_pools, library
    rid, lid, lesson = _reset()
    storage.programs_table.truncate()          # no runs: the library may be deleted
    gate = threading.Event()

    def call(tier, key, system, prompt, **kw):
        gate.wait(5)
        return _long()
    with patch.object(model_pools, 'call_pool_json', call):
        library_scripts.write(lid, storage.get_member('mom'))
        check(_wait(lambda: library_scripts.job_state(lid) is not None), 'running')
        check(library.delete(lid, storage.get_member('mom'))['status'] == 'success', 'deleted while in flight')
        gate.set()
        time.sleep(0.3)
    check(storage.get_library_scripts(lid) == [], 'no script reappeared')
    check(library_scripts.job_state(lid) is None, 'no job entry reappeared')
    check(storage.get_library_program(lid) is None, 'still gone')


def scenario_a_dead_entry_is_reclaimed_and_the_stale_thread_is_ignored():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    dead = {'job_id': 'old', 'started_at': time.time() - 4000, 'last_progress_at': time.time() - 1860,
            'total': 4, 'done': 1, 'failed': 0, 'lesson_id': lesson['id'], 'variant_label': 'Session A'}
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: dead})
    check(library_scripts.job_state(lid) is None, 'a dead entry reads as absent')
    call, calls = _fake_pool([_long()] * 4)
    with patch.object(model_pools, 'call_pool_json', call):
        res = library_scripts.write(lid, storage.get_member('mom'))
        check(res['status'] == 'ok' and res['job']['job_id'] != 'old', 'reclaimed with a new job id')
        check(_wait(lambda: library_scripts.job_state(lid) is None), 'cleared')
    # a stale thread's map update: nothing to update when the entry is another job's
    library_scripts._progress(lid, 'old', done=99)
    check((storage.get_app_state(library_scripts.JOBS_KEY) or {}).get(lid) is None, 'stale update dropped')


def scenario_two_libraries_both_start():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    rid2 = add_run({'member_id': 'sam', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **{**PIANO, 'title': 'Learn drums'}})
    lid2 = storage.get_program(rid2)['library_id']
    call, calls = _fake_pool([_long()] * 8)
    with patch.object(model_pools, 'call_pool_json', call):
        a = library_scripts.write(lid, storage.get_member('mom'))
        b = library_scripts.write(lid2, storage.get_member('mom'))
        check(a['status'] == 'ok' and b['status'] == 'ok', 'both started')
        check(_wait(lambda: library_scripts.job_state(lid) is None and library_scripts.job_state(lid2) is None), 'both ended')
    check(len(storage.get_library_scripts(lid)) == 4 and len(storage.get_library_scripts(lid2)) == 4, 'eight scripts')


def scenario_write_refuses_switches_and_children():
    from services import library_scripts
    rid, lid, lesson = _reset()
    with patch.object(storage, 'get_settings', lambda: {'program_lessons_enabled': False}):
        check(library_scripts.write(lid, storage.get_member('mom'))['message'] == 'Lesson scripts are switched off for this household.', 'switch')
    with patch.object(storage, 'get_settings', lambda: {'programs_enabled': False}):
        check(library_scripts.write(lid, storage.get_member('mom'))['message'] == 'Programs are switched off for this household.', 'switch')
    check(library_scripts.write(lid, storage.get_member('kate'))['code'] == 403, 'a child may not')
    check(library_scripts.write(lid, storage.get_member('aunt'))['code'] == 403, 'a non-creator adult may not')


def scenario_startup_clears_the_job_map():
    from services import library_scripts
    rid, lid, lesson = _reset()
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: {'job_id': 'x', 'started_at': time.time(), 'last_progress_at': time.time(),
                                                           'total': 2, 'done': 0, 'failed': 0}})
    library_scripts.clear_jobs()
    check(library_scripts.job_state(lid) is None, 'cleared')
    import inspect, main
    check('clear_jobs' in inspect.getsource(main.lifespan), 'the lifespan clears the map at startup')


def scenario_a_restart_keeps_written_scripts():
    from services import library_scripts
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data())
    library_scripts.clear_jobs()
    check(storage.get_library_script(lid, _slot(lesson))['scenes'] == SAY, 'written scripts survive a restart')
    check(library_scripts.needs_script(lid, _slot(lesson)) is False, 'and are not rewritten')


# --- nightly retry ---------------------------------------------------------------

def scenario_retry_due_claims_writes_and_skips_a_live_job():
    import datetime
    from services import library_scripts, model_pools, programs
    rid, lid, lesson = _reset()
    windows = [{'program_id': rid, 'date': (datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                'lesson_id': lesson['id'], 'variant_label': 'Session A'}]
    call, calls = _fake_pool([_long()] * 3)
    with patch.object(model_pools, 'call_pool_json', call), patch.object(programs, '_practice_windows', lambda start, end, member_id=None: windows):
        wrote = library_scripts.retry_due(datetime.datetime.now(), limit=6)
    check(wrote == 1 and len(calls) == 1 and storage.get_library_script(lid, _slot(lesson))['scenes'], 'written once')
    storage.delete_library_script(lid, _slot(lesson))
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: {'job_id': 'j', 'started_at': time.time(), 'last_progress_at': time.time(),
                                                           'total': 4, 'done': 0, 'failed': 0}})
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call), patch.object(programs, '_practice_windows', lambda start, end, member_id=None: windows):
        wrote = library_scripts.retry_due(datetime.datetime.now(), limit=6)
    check(wrote == 0 and not calls, 'a live job means the nightly pass skips that library')


def scenario_retry_due_shortfall_counts_against_the_pass():
    import datetime
    from services import library_scripts, model_pools, programs
    rid, lid, lesson = _reset()
    windows = [{'program_id': rid, 'date': (datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                'lesson_id': lesson['id'], 'variant_label': 'Session A'},
               {'program_id': rid, 'date': (datetime.date.today() + datetime.timedelta(days=2)).isoformat(),
                'lesson_id': lesson['id'], 'variant_label': 'Session B'}]
    call, calls = _fake_pool([_short(), _long(), _long()])
    with patch.object(model_pools, 'call_pool_json', call), patch.object(programs, '_practice_windows', lambda start, end, member_id=None: windows):
        library_scripts.retry_due(datetime.datetime.now(), limit=2)
    check(len(calls) == 2, f'the retry spent the second unit, Session B waits: {len(calls)}')
    check(storage.get_library_script(lid, _slot(lesson))['scenes'][0]['type'] == 'teach', 'the longer replaced')
    check(storage.get_library_script(lid, _slot(lesson, 'Session B')) is None, 'B not reached this pass')
    check(storage.program_lessons_table.all() == [], 'nothing written to program_lessons')


def scenario_generate_due_still_routes_through_the_marker_and_switches():
    import datetime
    from services import library_scripts
    rid, lid, lesson = _reset()
    storage.set_app_state('program_lessons_swept', '')
    with patch.object(library_scripts, 'retry_due', lambda now, limit: 7):
        check(pl.generate_due(datetime.datetime.now()) == 7, 'generate_due calls retry_due')
        check(pl.generate_due(datetime.datetime.now()) == 0, 'the day marker throttles')
    check(not hasattr(pl, 'sweep_report'), 'sweep_report is gone')


# --- migration -------------------------------------------------------------------

def scenario_migration_deletes_every_per_run_script_of_a_library_run():
    from services import migrations, library_scripts
    rid, lid, lesson = _reset()
    rid2 = add_run({'member_id': 'sam', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **PIANO})
    storage.update_program(rid2, {'library_id': lid})
    storage.program_lessons_table.insert({'id': 'a', 'program_id': rid, 'lesson_id': lesson['id'], 'variant_label': 'Session A',
                                          'origin': 'generated', 'scenes': [{'type': 'say', 'text': 'SECRET shy about playing'}],
                                          'edited': False, 'created_at': 1.0})
    storage.program_lessons_table.insert({'id': 'b', 'program_id': rid2, 'lesson_id': lesson['id'], 'variant_label': 'Session A',
                                          'origin': 'generated', 'scenes': [{'type': 'say', 'text': 'Mine'}], 'edited': True, 'created_at': 2.0})
    legacy = storage.add_program({'member_id': 'sam', 'title': 'Old', 'phases': [{'name': 'P', 'steps': ['x']}], 'state': 'active',
                                  'shape': {'minutes': 20, 'sessions_per_week': 2}, 'created_by': 'mom'})
    storage.program_lessons_table.insert({'id': 'c', 'program_id': legacy, 'phase_name': 'P', 'unit_n': 0, 'session_label': '',
                                          'origin': 'generated', 'scenes': [{'type': 'say', 'text': 'legacy'}], 'edited': False})
    with patch.object(migrations.logger, 'info') as info:
        migrations.migrate_library_scripts_v2499()
        logged = ' '.join(str(c) for c in info.call_args_list)
    left = [r['id'] for r in storage.program_lessons_table.all()]
    check(left == ['c'], f'only the unconverted run keeps its row, got {left}')
    check(rid2 in logged and lesson['id'] in logged, f'the edited row is logged by run and lesson id, got {logged}')
    check('Mine' not in logged and 'SECRET' not in logged, 'never its text')
    check(storage.get_library_scripts(lid) == [], 'nothing was written to the library')
    migrations.migrate_library_scripts_v2499()
    check([r['id'] for r in storage.program_lessons_table.all()] == ['c'], 'a second run is a no-op')
    run = storage.get_program(rid)
    check(library_scripts.script_for_run(run, lesson['id'], 'Session A') is None, 'the run reads no old script')


# --- routes ----------------------------------------------------------------------

def _client():
    import main
    return TestClient(main.app), main


def _hdr(mid):
    return {'x-member-token': storage.create_member_token(mid)}


def scenario_run_routes_fill_and_share_one_script():
    rid, lid, lesson = _reset()
    rid2 = add_run({'member_id': 'sam', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **PIANO})
    storage.update_program(rid2, {'library_id': lid})
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=[{'type': 'say', 'text': 'Sit down, {name}, for {project}.', 'speak': 'Go {name}'}]))
    c, main = _client()
    qs = f"lesson_id={lesson['id']}&variant_label=Session%20A"
    a = c.get(f'/api/programs/{rid}/lesson?{qs}', headers=_hdr('mom')).json()['lesson']
    b = c.get(f'/api/programs/{rid2}/lesson?{qs}', headers=_hdr('mom')).json()['lesson']
    check(a['scenes'][0]['text'] == "Sit down, D'Arcy, for Piano for Kate." and a['scenes'][0]['speak'] == "Go D'Arcy", f'filled: {a}')
    check(b['scenes'][0]['text'] == 'Sit down, Sam, for Piano for Kate.', 'the other run, the same template')
    check('model' not in a and a['minutes'] == 1, f'no model name, minutes present: {a.keys()}')
    wall = c.get(f'/api/programs/{rid}/lesson-scenes?{qs}').json()['lesson']
    check(wall['scenes'][0]['text'].startswith("Sit down, D'Arcy"), f'a panel gets filled scenes, got {wall}')
    v = c.post('/api/lessons/voice', json={'text': "Sit down, D'Arcy, for Piano for Kate.", 'lang': ''})
    check(v.status_code != 400, 'the filled line passes the voice route screens')


def scenario_fill_keeps_names_verbatim():
    rid, lid, lesson = _reset()
    out = pl.fill([{'type': 'say', 'text': 'Hi {name}', 'speak': '{name}!'}], {'name': "D'Arcy Zoë", 'project': 'P'})
    check(out[0]['text'] == "Hi D'Arcy Zoë" and out[0]['speak'] == "D'Arcy Zoë!", f'verbatim, got {out}')
    out = pl.fill([{'type': 'say', 'text': 'Hi {name}'}], {'name': '', 'project': 'P'})
    check(out[0]['text'] == 'Hi you', 'an empty name says you')


def scenario_legacy_run_writes_answer_409_for_a_library_run():
    rid, lid, lesson = _reset()
    c, main = _client()
    body = {'member_id': 'mom', 'lesson_id': lesson['id'], 'variant_label': 'Session A', 'scenes': SAY}
    r = c.put(f'/api/programs/{rid}/lesson', json=body, headers=_hdr('mom'))
    check(r.status_code == 409 and r.json()['detail'] == 'Scripts live in the library.', f'PUT 409, got {r.status_code} {r.text}')
    r = c.delete(f"/api/programs/{rid}/lesson?lesson_id={lesson['id']}&variant_label=Session%20A", headers=_hdr('mom'))
    check(r.status_code == 409, 'DELETE 409')
    r = c.post('/api/programs/lessons/sweep', json={'member_id': 'mom'}, headers=_hdr('mom'))
    check(r.status_code in (404, 405), f'the sweep route is gone, got {r.status_code}')
    from services import auth
    check(not any('/api/programs/lessons/sweep' in str(rule) for rule in auth.RULES), 'and gone from the auth table')


def scenario_library_script_routes_and_who_may():
    rid, lid, lesson = _reset()
    c, main = _client()
    path = f"/api/library/{lid}/lessons/{lesson['id']}/script?variant_label=Session%20A"
    check(c.get(path, headers=_hdr('kate')).json()['script'] is None, 'a member reads: nothing yet')
    r = c.put(path, json={'scenes': [{'type': 'say', 'text': 'Hi {name}'}] * 20}, headers=_hdr('mom'))
    check(r.status_code == 200 and r.json()['status'] == 'ok', f'a parent edits, got {r.text}')
    got = c.get(path, headers=_hdr('kate')).json()['script']
    check(len(got['scenes']) == 20 and got['edited'] and got['scenes'][0]['text'] == 'Hi {name}', f'template, cap by profile (30), got {len(got["scenes"])}')
    filled = c.get(path + '&fill=1', headers=_hdr('kate')).json()['script']
    check(filled['scenes'][0]['text'] == "Hi D'Arcy", 'preview fills with the viewer')
    for who in ('kate', 'aunt'):
        check(c.put(path, json={'scenes': SAY}, headers=_hdr(who)).status_code == 403, f'{who} may not edit')
        check(c.delete(path, headers=_hdr(who)).status_code == 403, f'{who} may not delete')
        check(c.post(f'/api/library/{lid}/scripts/write', json={}, headers=_hdr(who)).status_code == 403, f'{who} may not write')
    r = c.put(path, json={'scenes': [{'type': 'say', 'text': 'x'}] * 31}, headers=_hdr('mom'))
    check(len(c.get(path, headers=_hdr('mom')).json()['script']['scenes']) == 30, 'PUT honours scene_cap(30)')
    check(c.delete(path, headers=_hdr('mom')).json()['status'] == 'ok', 'a parent deletes')
    from services import library_scripts
    with patch.object(library_scripts, 'write', lambda lid_, actor, **kw: {'status': 'ok', 'job': {'job_id': 'j', 'total': 4, 'done': 0}}):
        r = c.post(f'/api/library/{lid}/scripts/write', json={}, headers=_hdr('mom'))
    check(r.status_code == 202 and r.json()['job']['total'] == 4, f'202 with the job, got {r.status_code} {r.text}')


def scenario_library_view_carries_script_state():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(minutes=12))
    t = storage.claim_library_script(lid, _slot(lesson, 'Session B'))
    storage.commit_library_script(lid, _slot(lesson, 'Session B'), t, _data(scenes=[], attempts=1, note='pool empty'))
    from services import library, library_scripts
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: {'job_id': 'j', 'started_at': time.time(), 'last_progress_at': time.time(),
                                                           'total': 4, 'done': 2, 'failed': 1, 'lesson_id': lesson['id'], 'variant_label': ''}})
    view = library.get(lid, storage.get_member('kate'))
    s = view['scripts'][lesson['id']]
    check(s['Session A']['state'] == 'ready' and s['Session A']['minutes'] == 12, f'ready, got {s}')
    check(s['Session B']['state'] == 'failed' and s['Session B']['note'] == 'pool empty', 'failed with note')
    check(view['writing']['done'] == 2 and view['writing']['total'] == 4, 'job on the view')
    other = view['scripts'][storage.get_library_program(lid)['lessons'][1]['id']]
    check(other['Session A']['state'] == 'none', 'no script yet')


def scenario_lesson_help_reads_a_teach_beat_through_the_resolver():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=pl.sanitize_script(TEACH, 'generated', minutes=30)))
    c, main = _client()
    from services import model_pools
    seen = {}

    def call(tier, key, system, prompt, **kw):
        seen['prompt'] = prompt
        return {'answer': 'Step left of the two black keys.'}
    with patch.object(model_pools, 'call_pool_json', call), patch.object(model_pools, 'credentials', lambda t, s: ('m', 'k')):
        r = c.post(f'/api/programs/{rid}/lesson-help', json={'lesson_id': lesson['id'], 'variant_label': 'Session A', 'scene_idx': 0},
                   headers=_hdr('mom'))
    check(r.status_code == 200 and 'two black keys' in seen['prompt'] and 'Play C, rest, C' in seen['prompt'], f'the teach beat, got {seen}')


if __name__ == '__main__':
    scenario_claim_then_commit_then_nobody_else()
    scenario_failure_record_lands_only_on_an_empty_slot()
    scenario_commit_after_library_delete_archive_or_lesson_removal_is_dropped()
    scenario_replace_is_in_place_and_conditional()
    scenario_an_edit_during_a_job_wins()
    scenario_delete_invalidates_every_token()
    scenario_a_short_script_is_stored_then_retried_once_and_replaced()
    scenario_retry_needs_allowance_and_a_worse_second_changes_nothing()
    scenario_a_full_length_script_costs_one_call_and_resets_attempts()
    scenario_the_pool_setting_picks_the_tier()
    scenario_the_prompt_carries_the_spine()
    scenario_a_cited_lesson_still_needs_its_page()
    scenario_write_runs_every_lesson_in_order_and_clears()
    scenario_regenerate_one_deletes_then_claims_and_writes_that_one()
    scenario_job_result_after_edit_is_dropped()
    scenario_delete_mid_call_leaves_nothing()
    scenario_a_dead_entry_is_reclaimed_and_the_stale_thread_is_ignored()
    scenario_two_libraries_both_start()
    scenario_write_refuses_switches_and_children()
    scenario_startup_clears_the_job_map()
    scenario_a_restart_keeps_written_scripts()
    scenario_retry_due_claims_writes_and_skips_a_live_job()
    scenario_retry_due_shortfall_counts_against_the_pass()
    scenario_generate_due_still_routes_through_the_marker_and_switches()
    scenario_migration_deletes_every_per_run_script_of_a_library_run()
    scenario_run_routes_fill_and_share_one_script()
    scenario_fill_keeps_names_verbatim()
    scenario_legacy_run_writes_answer_409_for_a_library_run()
    scenario_library_script_routes_and_who_may()
    scenario_library_view_carries_script_state()
    scenario_lesson_help_reads_a_teach_beat_through_the_resolver()
    print('test_library_scripts OK')
