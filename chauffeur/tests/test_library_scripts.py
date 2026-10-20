"""Program-owned lesson scripts (spec 2026-10-20-lesson-depth-design.md rev 3, sections 1, 2, 6, 7).

Pinned here: the five storage doors and their claim tokens; the job and its ownership; the
nightly retry; the migration; the run routes reading through one resolver with variables
filled; the library script routes and who may use them.

Run from chauffeur/:  python tests/test_library_scripts.py   (HA_BASE_URL unset)
"""
import ast
import copy
import inspect
import json
import textwrap
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
PIANO3 = copy.deepcopy(PIANO)
PIANO3['phases'][0]['units'].append({'n': 3, 'title': 'Both hands', 'sessions': 1, 'body': 'Hands together on C.'})
CURATED = {'phases': copy.deepcopy(PIANO['phases']), 'source': {'origin': 'generated', 'reason': 'test'}}
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


def _legacy_run(rid='legacy-run', member='sam', title='Old drums'):
    """A run exactly as the pre-library code stored it: no library_id, the curriculum on the row.
    Written past every door, as test_library_migration's `_legacy` does, because storage.add_program
    validates through Program, which no longer carries `title` or `phases` at all."""
    storage.programs_table.insert({
        'id': rid, 'member_id': member, 'title': title, 'state': 'active', 'created_by': 'mom',
        'starting_point': '', 'sessions': [], 'progress': {},
        'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': [], 'slots': []},
        'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None,
                     'rebaselined_at': None, 'rebaselines': 0},
        'emissions': {'commitment_ids': [], 'thread_ids': [], 'event_ids': []},
        'phases': [{'name': 'P', 'weeks': 2, 'what': 'Beats', 'steps': ['Rock beat']}]})
    row = storage.get_program(rid)
    check(row.get('library_id') is None and [p.get('name') for p in row.get('phases') or []] == ['P'],
          f'the historical row keeps its own curriculum and names no library, got {row}')
    return rid


def _spawned(before):
    """The threads started since `before` was taken: a job's worker."""
    return [th for th in threading.enumerate() if th not in before]


def _join(threads, s=5.0):
    for th in threads:
        th.join(s)
    check(threads and not any(th.is_alive() for th in threads), f'the worker thread finished, got {threads}')


def _raw_jobs():
    from services import library_scripts
    return storage.get_app_state(library_scripts.JOBS_KEY) or {}


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


def _first_then(second, lid, lesson, label='Session A'):
    """A pool that answers a short script first and `second` next. On the second call it records
    what storage already holds for the slot, so a test sees the first script was committed before
    the retry ever answered."""
    calls, held = [], []

    def call(tier, key, system, prompt, **kw):
        calls.append({'tier': tier, 'system': system, 'prompt': prompt})
        if len(calls) == 1:
            return _short()
        held.append(storage.get_library_script(lid, _slot(lesson, label)))
        return second
    return call, calls, held


def scenario_a_short_script_is_stored_then_retried_once_and_replaced():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    call, calls, held = _first_then(_long(), lid, lesson)
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'})
    check(len(calls) == 2, f'one retry, got {len(calls)}')
    first = held[0] if held else None
    want = pl.sanitize_script(SAY, 'generated', minutes=30)
    check(first and first['scenes'] == want and first['attempts'] == 0,
          f'the first script is committed before the retry answers, got {first}')
    est_min = int(round(pl.estimate_seconds(want) / 60))
    check(first['minutes'] == est_min and first['note'] == f'runs about {est_min} minutes of 30',
          f'with its own estimate and the shortfall note, got {first}')
    check('runs about' in calls[1]['prompt'] and 'of the 30 asked' in calls[1]['prompt'], f'shortfall named: {calls[1]["prompt"][-200:]}')
    check(row and row['scenes'][0]['type'] == 'teach', 'the longer result replaced the first')
    check(row['id'] == first['id'] and row['claim'] and row['claim'] != first['claim'],
          f'replaced in place with a new claim, got {row}')
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
    for label, second in (('a shorter script', {'scenes': [{'type': 'say', 'text': 'Go.'}]}),
                          ('an ordinary error', {'error': 'boom'}),
                          ('a transient error', {'error': 'boom', 'transient': True}),
                          ('a deferred call', {'error': 'paused', 'deferred': True})):
        storage.delete_library_script(lid, _slot(lesson))
        call, calls, held = _first_then(second, lid, lesson)
        with patch.object(model_pools, 'call_pool_json', call):
            row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                                  {'llm_gemini_api_key': 'k'})
        check(len(calls) == 2, f'{label}: the retry was asked, got {len(calls)} calls')
        first = held[0] if held else None
        check(first and first['scenes'] and first['attempts'] == 0, f'{label}: the first script was stored first, got {first}')
        now = storage.get_library_script(lid, _slot(lesson))
        check(now == first, f'{label}: the stored first row is unchanged, claim and attempts included: {first} -> {now}')
        check(row == first, f'{label}: and generate_script hands back that same row, got {row}')


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
    for needle in ('OPEN', 'TEACH', 'WORK', 'WRAP', '"type":"teach"', 'movement', 'cooking', 'phonics', 'problem-shaped',
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


def scenario_the_job_skips_ready_edited_and_exhausted_and_counts_as_it_goes():
    from services import library_scripts, model_pools
    _reset()
    rid = add_run({'member_id': 'sam', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **{**PIANO3, 'title': 'Learn organ'}})
    lid = storage.get_program(rid)['library_id']
    l1, l2, l3 = storage.get_library_program(lid)['lessons']
    t = storage.claim_library_script(lid, _slot(l1))
    storage.commit_library_script(lid, _slot(l1), t, _data())                                        # ready
    storage.edit_library_script(lid, _slot(l1, 'Session B'), _data(scenes=[{'type': 'say', 'text': 'Mine'}]))   # edited
    t = storage.claim_library_script(lid, _slot(l2))
    storage.commit_library_script(lid, _slot(l2), t, _data(scenes=[], attempts=3, note='gave up'))     # exhausted at the default 3
    skipped = {name: (slot, storage.get_library_script(lid, slot)) for name, slot in
               (('ready', _slot(l1)), ('edited', _slot(l1, 'Session B')), ('exhausted', _slot(l2)))}
    started = [threading.Event() for _ in range(3)]
    release = [threading.Event() for _ in range(3)]
    answers = [{'error': 'boom'}, _long(), _long()]
    seen, lock = [], threading.Lock()

    def call(tier, key, system, prompt, **kw):
        with lock:
            i = len(seen)
            seen.append(prompt)
        if i < 3:
            started[i].set()
            release[i].wait(5)
            return answers[i]
        return {'error': 'unexpected fourth call'}
    with patch.object(model_pools, 'call_pool_json', call):
        before = set(threading.enumerate())
        res = library_scripts.write(lid, storage.get_member('mom'))
        workers = _spawned(before)
        check(res['status'] == 'ok' and res['job']['total'] == 3, f'only the three slots lacking a script, got {res}')
        check(started[0].wait(5), 'first call in flight')
        e0 = _raw_jobs()[lid]
        check(e0['done'] == 0 and e0['failed'] == 0 and e0['lesson_id'] == l2['id'] and e0['variant_label'] == 'Session B',
              f'the entry names the lesson being written, got {e0}')
        time.sleep(0.05)
        release[0].set()
        check(started[1].wait(5), 'second call in flight')
        e1 = _raw_jobs()[lid]
        check(e1['done'] == 1 and e1['failed'] == 1 and e1['last_progress_at'] > e0['last_progress_at']
              and e1['lesson_id'] == l3['id'] and e1['variant_label'] == 'Session A', f'a failure counts and progress moves, got {e1}')
        time.sleep(0.05)
        release[1].set()
        check(started[2].wait(5), 'third call in flight')
        e2 = _raw_jobs()[lid]
        check(e2['done'] == 2 and e2['failed'] == 1 and e2['last_progress_at'] > e1['last_progress_at']
              and e2['lesson_id'] == l3['id'] and e2['variant_label'] == 'Session B', f'a success counts and progress moves, got {e2}')
        release[2].set()
        _join(workers)
    check(library_scripts.job_state(lid) is None and lid not in _raw_jobs(), 'the entry is cleared at the end')
    for name, (slot, row) in skipped.items():
        check(storage.get_library_script(lid, slot) == row, f'the {name} slot is untouched')
    failed = storage.get_library_script(lid, _slot(l2, 'Session B'))
    check(failed and not failed['scenes'] and failed['attempts'] == 1, f'the hard error is one recorded attempt, got {failed}')
    check(all(storage.get_library_script(lid, _slot(l3, lab))['scenes'] for lab in ('Session A', 'Session B')),
          'both lesson-three slots are written')
    check(len(seen) == 3, f'only the three eligible slots spent a call, got {len(seen)}')


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


def _blocking_pool():
    """Signals when a call has started and holds it until released; later calls pass straight through."""
    started, release, calls = threading.Event(), threading.Event(), []

    def call(tier, key, system, prompt, **kw):
        calls.append(prompt)
        started.set()
        release.wait(5)
        return _long()
    return call, started, release, calls


def scenario_delete_mid_call_leaves_nothing():
    from services import library_scripts, model_pools, library
    rid, lid, lesson = _reset()
    storage.programs_table.truncate()          # no runs: the library may be deleted
    mom = storage.get_member('mom')
    call, started, release, calls = _blocking_pool()
    with patch.object(model_pools, 'call_pool_json', call):
        before = set(threading.enumerate())
        check(library_scripts.write(lid, mom)['status'] == 'ok', 'started')
        workers = _spawned(before)
        check(started.wait(5), 'the model call is in flight')
        check(library.delete(lid, mom)['status'] == 'success', 'deleted while in flight')
        release.set()
        _join(workers)
    check(storage.get_library_scripts(lid) == [], 'no script reappeared')
    check(lid not in _raw_jobs(), f'no job entry reappeared in the raw map, got {_raw_jobs()}')
    check(storage.get_library_program(lid) is None, 'still gone')
    check(len(calls) == 1, f'no further lesson was attempted, got {len(calls)} calls')


def scenario_archive_mid_call_drops_the_result_and_ends_the_job():
    from services import library_scripts, model_pools, library
    rid, lid, lesson = _reset()
    mom = storage.get_member('mom')
    call, started, release, calls = _blocking_pool()
    with patch.object(model_pools, 'call_pool_json', call):
        before = set(threading.enumerate())
        check(library_scripts.write(lid, mom)['status'] == 'ok', 'started')
        workers = _spawned(before)
        check(started.wait(5), 'the model call is in flight')
        check(library.archive(lid, mom)['status'] == 'success', 'archived while in flight')
        release.set()
        _join(workers)
    check(not any(r.get('scenes') for r in storage.get_library_scripts(lid)), 'the in-flight result was dropped')
    check(lid not in _raw_jobs(), f'the job ended and cleared its entry, got {_raw_jobs()}')
    check(len(calls) == 1, f'no further lesson was attempted on an archived library, got {len(calls)} calls')
    check(storage.get_library_program(lid)['archived'], 'and the library stays archived')


def scenario_a_dead_entry_is_reclaimed_and_the_stale_thread_is_ignored():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    dead = {'job_id': 'old', 'started_at': time.time() - 4000, 'last_progress_at': time.time() - 1860,
            'total': 4, 'done': 1, 'failed': 0, 'lesson_id': lesson['id'], 'variant_label': 'Session A'}
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: dead})
    check(library_scripts.job_state(lid) is None, 'a dead entry reads as absent')
    storage.set_app_state(library_scripts.JOBS_KEY, {})
    # A real old worker, blocked inside its first model call; then its entry goes 31 minutes stale.
    started = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    seen, lock = [], threading.Lock()

    def call(tier, key, system, prompt, **kw):
        with lock:
            i = len(seen)
            seen.append(prompt)
        if i < 2:
            started[i].set()
            release[i].wait(5)
        return _long()
    mom = storage.get_member('mom')
    with patch.object(model_pools, 'call_pool_json', call):
        before = set(threading.enumerate())
        old = library_scripts.write(lid, mom)
        old_threads = _spawned(before)
        check(old['status'] == 'ok' and started[0].wait(5), f'the old worker is inside its first call, got {old}')
        old_id = old['job']['job_id']
        jobs = _raw_jobs()
        jobs[lid]['last_progress_at'] = time.time() - 1860
        storage.set_app_state(library_scripts.JOBS_KEY, jobs)
        check(library_scripts.job_state(lid) is None, 'its entry now reads as dead')
        before = set(threading.enumerate())
        new = library_scripts.write(lid, mom)
        new_threads = _spawned(before)
        check(new['status'] == 'ok' and new['job']['job_id'] != old_id, f'reclaimed with a new job id, got {new}')
        check(started[1].wait(5), 'the replacement is inside its first call')
        claim = storage.get_library_script(lid, _slot(lesson))['claim']
        release[0].set()
        _join(old_threads)
        entry = _raw_jobs().get(lid) or {}
        check(entry.get('job_id') == new['job']['job_id'], f'the old worker never touched the new entry, got {entry}')
        row = storage.get_library_script(lid, _slot(lesson))
        check(row['claim'] == claim and not row['scenes'], f"the old worker's result was refused by the token, got {row}")
        release[1].set()
        _join(new_threads)
    check(library_scripts.job_state(lid) is None and lid not in _raw_jobs(), 'the replacement cleared its own entry')
    rows = storage.get_library_scripts(lid)
    check(len(rows) == 4 and all(r['scenes'] for r in rows), f'the replacement wrote every lesson, got {len(rows)}')
    check(len(seen) == 5, f'the old worker made no second call after it lost the job, got {len(seen)} calls')
    # and a stale map update after the fact: nothing to update when the entry is not this job's
    library_scripts._progress(lid, old_id, done=99)
    check(_raw_jobs().get(lid) is None, 'stale update dropped')


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


def _write_spy():
    calls = []

    def spy(library_id, actor, *a, **kw):
        calls.append(library_id)
        return {'status': 'ok', 'job': {'job_id': 'j', 'total': 0, 'done': 0, 'failed': 0}}
    return spy, calls


def scenario_a_new_library_row_schedules_one_write_and_lesson_edits_schedule_none():
    """Spec section 6, Triggers: library.create (hand), the run picker's make-new branch of
    POST /api/programs (hand; controller ruling 2026-10-20), the run edit's Look again (recurate) and
    Argyle's propose_program each start the job for the row they minted, once; add_lesson and
    update_lesson start nothing. propose_program does not go through library.create (it mints in
    agent_tools_v2._start_program_choice with storage.add_library_program); that helper names the
    row and schedules nothing (Task 4 review ruling), and its two callers are pinned in
    scenario_argyle_schedules_a_new_row_after_its_transaction."""
    from services import library_scripts, library, programs_curate, agent_tools_v2
    rid, lid, lesson = _reset()
    mom = storage.get_member('mom')
    spy, calls = _write_spy()
    with patch.object(library_scripts, 'write', spy), \
            patch.object(programs_curate, 'curate', lambda *a, **kw: copy.deepcopy(CURATED)):
        made = library.create({'title': 'Learn violin', 'minutes': 30, 'sessions_per_week': 3,
                               'age_band': 'any', 'assumes': ''}, mom)
        check(made['status'] == 'success', f'created, got {made}')
        check(calls == [made['program']['id']], f'library.create schedules its new row once, got {calls}')
        del calls[:]
        c, main = _client()
        r = c.post('/api/programs', headers=_hdr('mom'),
                   json={'project_id': 'prj', 'for_member_id': 'kate', 'title': 'Learn flute', 'minutes': 30,
                         'sessions_per_week': 3, 'assumes': '', 'starting_point': ''})
        check(r.status_code == 200 and r.json().get('status') == 'success', f'make a new one: {r.status_code} {r.text[:300]}')
        flute_lid = storage.get_program(r.json()['id'])['library_id']
        check(flute_lid not in (lid, made['program']['id']), 'the run picker minted its own new library row')
        check(calls == [flute_lid], f"POST /api/programs' make-new branch schedules its new row once, got {calls}")
        del calls[:]
        pid = add_run({'member_id': 'kate', 'created_by': 'mom', 'project_id': 'prj', 'state': 'proposed', **PIANO})
        old_lid = storage.get_program(pid)['library_id']
        r = c.post(f'/api/programs/{pid}/edit', json={'member_id': 'mom', 'recurate': True}, headers=_hdr('mom'))
        new_lid = storage.get_program(pid)['library_id']
        check(r.status_code == 200 and r.json().get('status') == 'success' and new_lid != old_lid,
              f'Look again minted a new library row, got {r.status_code} {r.text[:300]}')
        check(calls == [new_lid], f'and scheduled exactly that row once, got {calls}')
        del calls[:]
        profile = library.public_profile({'minutes': 30, 'sessions_per_week': 3, 'age_band': 'any', 'assumes': ''})
        prepared = {'status': 'success', 'message': '',
                    'program': library.from_curated('Learn cello', profile, copy.deepcopy(CURATED), 'mom')}
        choice = {'title': 'Learn cello', 'member_id': 'kate', 'starting_point': '', 'project_id': 'prj', 'created_by': 'mom',
                  'shape': {'minutes': 30, 'sessions_per_week': 3, 'preferred_days': []},
                  'profile': {'title': 'Learn cello', 'minutes': 30, 'sessions_per_week': 3, 'assumes': '', 'age_band': 'any'}}
        # Task 4 review ruling: the job never starts inside a caller's open transaction, so the
        # shared helper only returns the new row's id and schedules nothing itself; its callers
        # schedule after it returns (scenario_argyle_schedules_a_new_row_after_its_transaction).
        out = agent_tools_v2._start_program_choice(choice, mom, make_new=True, prepared=prepared)
        check(out.get('status') == 'success', f'Argyle started a run on a new row, got {out}')
        argyle_lid = storage.get_program(out['run_id'])['library_id']
        check(out.get('library_id') == argyle_lid, f'and names the new row it minted, got {out}')
        check(calls == [], f'_start_program_choice itself schedules nothing, got {calls}')
        phase_id = storage.get_library_program(lid)['phases'][0]['id']
        check(library.add_lesson(lid, {'phase_id': phase_id, 'title': 'Scales', 'steps': ['C major']}, mom)['status'] == 'success',
              'a lesson added')
        check(library.update_lesson(lid, lesson['id'], {'title': 'Middle C again'}, mom)['status'] == 'success', 'a lesson edited')
        check(calls == [], f'neither add_lesson nor update_lesson schedules a write, got {calls}')


def scenario_write_refuses_switches_and_children():
    from services import library_scripts
    rid, lid, lesson = _reset()
    with patch.object(storage, 'get_settings', lambda: {'program_lessons_enabled': False}):
        check(library_scripts.write(lid, storage.get_member('mom'))['message'] == 'Lesson scripts are switched off for this household.', 'switch')
    with patch.object(storage, 'get_settings', lambda: {'programs_enabled': False}):
        check(library_scripts.write(lid, storage.get_member('mom'))['message'] == 'Programs are switched off for this household.', 'switch')
    check(library_scripts.write(lid, storage.get_member('kate'))['code'] == 403, 'a child may not')
    check(library_scripts.write(lid, storage.get_member('aunt'))['code'] == 403, 'a non-creator adult may not')


def scenario_write_refuses_an_archived_library():
    """An archived program writes nothing: Regenerate must not delete a ready script first, and
    Write lessons must not start a job (spec section 6, commit-time admission refuses archived)."""
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    mom = storage.get_member('mom')
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data())
    storage.update_library_program(lid, {'archived': True})
    call, calls = _fake_pool([_long()] * 4)
    with patch.object(model_pools, 'call_pool_json', call):
        one = library_scripts.write(lid, mom, lesson_id=lesson['id'], variant_label='Session A')
        every = library_scripts.write(lid, mom)
    want = {'status': 'error', 'message': 'This program is archived.'}
    check(one == want, f'Regenerate on an archived program is refused in words, with no code, got {one}')
    check(every == want, f'and so is Write lessons, got {every}')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row and row['scenes'] == SAY, f'the ready script was not deleted, got {row}')
    check(library_scripts.job_state(lid) is None and lid not in _raw_jobs(), 'no job was started')
    check(not calls, f'and nothing was spent, got {len(calls)} calls')


def scenario_startup_clears_the_job_map():
    from services import library_scripts
    rid, lid, lesson = _reset()
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: {'job_id': 'x', 'started_at': time.time(), 'last_progress_at': time.time(),
                                                           'total': 2, 'done': 0, 'failed': 0}})
    library_scripts.clear_jobs()
    check(library_scripts.job_state(lid) is None and _raw_jobs() == {}, 'cleared')
    import main
    tree = ast.parse(textwrap.dedent(inspect.getsource(main.lifespan)))
    clears = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
              and ((isinstance(n.func, ast.Attribute) and n.func.attr == 'clear_jobs')
                   or (isinstance(n.func, ast.Name) and n.func.id == 'clear_jobs'))]
    yields = [n.lineno for n in ast.walk(tree) if isinstance(n, (ast.Yield, ast.YieldFrom))]
    check(clears, 'the lifespan body makes a real clear_jobs() call (a comment or a string does not count)')
    check(not yields or min(clears) < min(yields), f'and makes it at startup, before the yield: {clears} vs {yields}')


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


def scenario_the_nightly_pass_writes_library_scripts_and_keeps_the_legacy_branch():
    """generate_due: a library run's window is written to library_scripts through retry_due; an
    unconverted run's window still goes through generate_for into its own program_lessons row."""
    import datetime
    from services import model_pools, programs
    rid, lid, lesson = _reset()
    legacy = _legacy_run()
    day = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    windows = [{'program_id': rid, 'date': day, 'lesson_id': lesson['id'], 'variant_label': 'Session A'},
               {'program_id': legacy, 'date': day, 'phase_name': 'P', 'session_label': '', 'steps': ['Rock beat']}]
    storage.set_app_state('program_lessons_swept', '')
    call, calls = _fake_pool([_long(), _long(), _long()])
    with patch.object(model_pools, 'call_pool_json', call), \
            patch.object(programs, '_practice_windows', lambda start, end, member_id=None: windows):
        wrote = pl.generate_due(datetime.datetime.now())
    check(wrote == 2 and len(calls) == 2, f'one library script and one legacy lesson, got {wrote} written, {len(calls)} calls')
    check(storage.get_library_script(lid, _slot(lesson))['scenes'], 'the library run is written to library_scripts')
    rows = storage.program_lessons_table.all()
    check([r['program_id'] for r in rows] == [legacy] and rows[0]['scenes'] and rows[0].get('phase_name') == 'P',
          f'the unconverted run keeps its legacy row, and only it does, got {rows}')


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

def _private_reads(c, main, run_id, lesson, name):
    """GET lesson (signed in), lesson-scenes (an anonymous panel) and lesson-help (prompt captured):
    each reads only the shared library script, filled for the run's member."""
    from services import model_pools
    qs = f"lesson_id={lesson['id']}&variant_label=Session%20A"
    got = c.get(f'/api/programs/{run_id}/lesson?{qs}', headers=_hdr('mom')).json()
    wall = c.get(f'/api/programs/{run_id}/lesson-scenes?{qs}').json()
    seen = {}

    def call(tier, key, system, prompt, **kw):
        seen['prompt'] = prompt
        return {'answer': 'Sit tall and start.'}
    main._lesson_help_at = {}
    storage.set_app_state('lesson_help_used', {})
    with patch.object(model_pools, 'call_pool_json', call), patch.object(model_pools, 'credentials', lambda t, s: ('m', 'k')):
        h = c.post(f'/api/programs/{run_id}/lesson-help',
                   json={'lesson_id': lesson['id'], 'variant_label': 'Session A', 'scene_idx': 0})
    check(h.status_code == 200 and 'prompt' in seen, f'lesson-help answered from a prompt, got {h.status_code} {h.text}')
    blob = json.dumps(got) + json.dumps(wall) + json.dumps(h.json()) + seen['prompt']
    for secret in ('SECRET', 'shy about playing', 'Mine'):
        check(secret not in blob, f'{secret!r} is gone from every read of {run_id}')
    want = f'Shared start, {name}.'
    check(got['lesson']['scenes'][0]['text'] == want and wall['lesson']['scenes'][0]['text'] == want
          and 'Shared start' in seen['prompt'], f'all three read the shared script for {name}: {got} {wall} {seen}')


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
    legacy = _legacy_run()
    storage.program_lessons_table.insert({'id': 'c', 'program_id': legacy, 'phase_name': 'P', 'unit_n': 0, 'session_label': '',
                                          'origin': 'generated', 'scenes': [{'type': 'say', 'text': 'legacy'}], 'edited': False})
    with patch.object(migrations.logger, 'info') as info:
        migrations.migrate_library_scripts_v2499()
        logged = ' '.join(str(c) for c in info.call_args_list)
    left = [r['id'] for r in storage.program_lessons_table.all()]
    check(left == ['c'], f'only the unconverted run keeps its row, got {left}')
    check([p['name'] for p in storage.get_program(legacy).get('phases') or []] == ['P'], 'and its curriculum is untouched')
    check(rid2 in logged and lesson['id'] in logged, f'the edited row is logged by run and lesson id, got {logged}')
    check('Mine' not in logged and 'SECRET' not in logged, 'never its text')
    check(storage.get_library_scripts(lid) == [], 'nothing was written to the library')
    migrations.migrate_library_scripts_v2499()
    check([r['id'] for r in storage.program_lessons_table.all()] == ['c'], 'a second run is a no-op')
    run = storage.get_program(rid)
    check(library_scripts.script_for_run(run, lesson['id'], 'Session A') is None, 'the run reads no old script')
    tree = ast.parse(textwrap.dedent(inspect.getsource(migrations.run_all_migrations)))
    refs = [(n.lineno, n.id if isinstance(n, ast.Name) else n.attr) for n in ast.walk(tree)
            if isinstance(n, (ast.Name, ast.Attribute))]
    first = [ln for ln, nm in refs if nm == 'migrate_program_library_v2499']
    later = [ln for ln, nm in refs if nm == 'migrate_library_scripts_v2499']
    check(first and later and min(later) > max(first),
          f'run_all_migrations runs the scripts migration after the library migration: {first} then {later}')
    # The private material is gone from every route, for the run's member and after a reassignment.
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=[{'type': 'say', 'text': 'Shared start, {name}.'}]))
    c, main = _client()
    _private_reads(c, main, rid, lesson, "D'Arcy")
    _private_reads(c, main, rid2, lesson, 'Sam')
    storage.update_program(rid, {'member_id': 'sam'})
    _private_reads(c, main, rid, lesson, 'Sam')


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
    from services import announce
    heard = []

    def clip(text, lang=''):
        heard.append((text, lang))
        return {'status': 'success', 'audio': b'ID3fake', 'content_type': 'audio/mpeg'}
    with patch.object(announce, 'voice_clip', clip):
        v = c.post('/api/lessons/voice', json={'text': a['scenes'][0]['text'], 'lang': ''})
    check(v.status_code == 200 and heard == [("Sit down, D'Arcy, for Piano for Kate.", '')],
          f'the filled line passes the voice route and reaches the backend verbatim, got {v.status_code} {heard}')


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
    # An adult who made the program may do all three; another adult may not.
    storage.add_member({'id': 'uncle', 'name': 'Uncle Bo', 'role': 'adult'})
    rid3 = add_run({'member_id': 'sam', 'created_by': 'aunt', 'project_id': 'prj', 'state': 'active', **{**PIANO, 'title': 'Learn ukulele'}})
    lid3 = storage.get_program(rid3)['library_id']
    check(storage.get_library_program(lid3)['created_by'] == 'aunt', 'the fixture library is the adult\'s own')
    l3 = storage.get_library_program(lid3)['lessons'][0]
    p3 = f"/api/library/{lid3}/lessons/{l3['id']}/script?variant_label=Session%20A"
    check(c.put(p3, json={'scenes': SAY}, headers=_hdr('uncle')).status_code == 403, 'another adult may not edit')
    check(c.delete(p3, headers=_hdr('uncle')).status_code == 403, 'another adult may not delete')
    check(c.post(f'/api/library/{lid3}/scripts/write', json={}, headers=_hdr('uncle')).status_code == 403, 'another adult may not write')
    r = c.put(p3, json={'scenes': SAY}, headers=_hdr('aunt'))
    check(r.status_code == 200 and r.json()['status'] == 'ok', f'the creating adult edits, got {r.status_code} {r.text}')
    check(c.get(p3, headers=_hdr('aunt')).json()['script']['edited'], 'and it is stored as a hand edit')
    check(c.delete(p3, headers=_hdr('aunt')).json()['status'] == 'ok' and c.get(p3, headers=_hdr('aunt')).json()['script'] is None,
          'the creating adult deletes')
    spy, calls = _write_spy()
    with patch.object(library_scripts, 'write', spy):
        r = c.post(f'/api/library/{lid3}/scripts/write', json={}, headers=_hdr('aunt'))
    check(r.status_code == 202 and calls == [lid3], f'the creating adult starts a write, got {r.status_code} {calls}')


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



def scenario_argyle_schedules_a_new_row_after_its_transaction():
    """Spec section 6, Triggers, with the Task 4 review ruling: the job never starts inside a
    caller's open transaction. propose_program's direct make-new path schedules the new row after
    _start_program_choice returns; planned.answer_program_choice's Make new schedules it after its
    `with db_lock, transaction()` block exits, on success only. Each exactly once. Reached the way
    test_library_flows.py reaches them (its fixture, curate stubbed); its global stubs are put back
    afterwards so the scenarios after this one see the real modules."""
    import test_library_flows as flows
    from services import library_scripts, agent_tools_v2 as tools, missions, web, threads, programs_curate
    saved = (missions._post, web.research, threads.draft_message, programs_curate.curate, storage.get_settings)
    spy, calls = _write_spy()

    def ids():
        return {r['id'] for r in storage.get_library_programs()}
    try:
        with patch.object(library_scripts, 'write', spy):
            flows._fresh()
            project = flows._project('mom', audience='private', title='Music at home')
            before = ids()
            res = tools.propose_program(title='Learn piano', for_member_name='Kate', sessions_per_week=3, minutes=20,
                                        acting_member=dict(flows.MOM), project_id=project['id'])
            made = ids() - before
            check(res.get('status') == 'success' and len(made) == 1, f'no match: Argyle made a new row, got {res}')
            check(calls == list(made), f'the direct path schedules that row once, after the helper returns, got {calls}')
            del calls[:]
            flows._fresh()
            flows._library()
            mid, _ = flows._staged()
            check(calls == [], f'a waiting choice schedules nothing, got {calls}')
            opts = flows._choice(mid)
            before = ids()
            r = flows._answer(mid, 'make_new', opts)
            made = ids() - before
            check(r.status_code == 200 and len(made) == 1, f'Make new through the card made one row, got {r.status_code} {r.text[:200]}')
            check(calls == list(made), f'answer_program_choice schedules it once, after its transaction, got {calls}')
            del calls[:]
            flows._answer(mid, 'make_new', opts)
            check(calls == [], f'a repeated Make new makes and schedules nothing more, got {calls}')
    finally:
        missions._post, web.research, threads.draft_message, programs_curate.curate, storage.get_settings = saved

def scenario_the_job_never_reaches_the_paid_key():
    """Lesson scripts are background-shaped work (spec section 6): the job and the nightly retry
    run on the free chain only. Every free model answers a 429 (the transient throttle that
    with_paid_fallback counts) with a pro key on file and paid fallback set to 'auto': the throttle
    is never noted, the pro key is never looked up, and the free chain is not cut after Flash (a
    Flash-Lite candidate follows the Flash models within the pool's max_models). Pins the
    behaviour, not a parameter name."""
    from services import library_scripts, model_pools, paid_fallback, llm
    rid, lid, lesson = _reset()
    storage.set_app_state(paid_fallback._STATE_KEY, {})
    paid_fallback._state = None
    settings = {'llm_gemini_api_key': 'free-key', 'llm_gemini_paid_api_key': 'pro-key',
                'llm_paid_fallback_mode': 'auto', 'llm_paid_fallback_failures': 1}
    tried, keys, throttles, pools = [], [], [], []
    real_key_for_pool = model_pools.api_key_for_pool

    def call_model(model, api_key, system, prompt, **kw):
        tried.append(model)
        keys.append(api_key)
        return {'error': '429 RESOURCE_EXHAUSTED: quota exceeded'}

    def key_for_pool(pool, s):
        pools.append(pool)
        return real_key_for_pool(pool, s)
    saved_cooldowns = dict(model_pools._cooldowns)
    try:
        with patch.object(llm, 'call_model', call_model), \
                patch.object(model_pools, '_maybe_discover', lambda *a, **k: None), \
                patch.object(model_pools, 'api_key_for_pool', key_for_pool), \
                patch.object(paid_fallback, 'note_throttle', lambda *a, **k: throttles.append(a)):
            out = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A', settings)
    finally:
        model_pools._cooldowns.clear()
        model_pools._cooldowns.update(saved_cooldowns)
    check(out is None, f'nothing usable came back, so nothing is stored as a script, got {out}')
    check(not throttles, f'the free-tier throttle is never noted for lesson work, got {len(throttles)} notes')
    check('pro' not in pools, f'the pro key is never looked up, got {pools}')
    check(keys and set(keys) == {'free-key'}, f'every attempt used the free key, got {set(keys)}')
    first_lite = next((i for i, m in enumerate(tried) if 'flash-lite' in m), None)
    check(first_lite is not None and first_lite > 0 and all('flash' in m and 'lite' not in m for m in tried[:first_lite]),
          f'the chain was not cut after Flash: a Flash-Lite candidate was tried after the Flash models, got {tried}')
    row = storage.get_library_script(lid, _slot(lesson)) or {}
    check(not row.get('scenes') and row.get('attempts', 0) == 0,
          f'a throttle is transient: no scenes and no attempt spent, got {row}')

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
    scenario_the_job_skips_ready_edited_and_exhausted_and_counts_as_it_goes()
    scenario_regenerate_one_deletes_then_claims_and_writes_that_one()
    scenario_job_result_after_edit_is_dropped()
    scenario_delete_mid_call_leaves_nothing()
    scenario_archive_mid_call_drops_the_result_and_ends_the_job()
    scenario_a_dead_entry_is_reclaimed_and_the_stale_thread_is_ignored()
    scenario_two_libraries_both_start()
    scenario_a_new_library_row_schedules_one_write_and_lesson_edits_schedule_none()
    scenario_write_refuses_switches_and_children()
    scenario_write_refuses_an_archived_library()
    scenario_startup_clears_the_job_map()
    scenario_a_restart_keeps_written_scripts()
    scenario_retry_due_claims_writes_and_skips_a_live_job()
    scenario_retry_due_shortfall_counts_against_the_pass()
    scenario_the_nightly_pass_writes_library_scripts_and_keeps_the_legacy_branch()
    scenario_generate_due_still_routes_through_the_marker_and_switches()
    scenario_migration_deletes_every_per_run_script_of_a_library_run()
    scenario_run_routes_fill_and_share_one_script()
    scenario_fill_keeps_names_verbatim()
    scenario_legacy_run_writes_answer_409_for_a_library_run()
    scenario_library_script_routes_and_who_may()
    scenario_library_view_carries_script_state()
    scenario_lesson_help_reads_a_teach_beat_through_the_resolver()
    scenario_argyle_schedules_a_new_row_after_its_transaction()
    scenario_the_job_never_reaches_the_paid_key()
    print('test_library_scripts OK')
