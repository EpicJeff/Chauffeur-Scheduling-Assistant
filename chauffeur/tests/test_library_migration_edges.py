"""Additional persisted-data edges; the seven-scenario migration contract is unchanged."""
import asyncio
import inspect
import json
import traceback
from unittest.mock import AsyncMock, Mock, patch

from test_library_migration import (
    check, storage, programs, migrations, _fresh, _legacy, _legacy_script, _migrate,
    _legacy_rung, _with_one_more, _current_title, _library_of,
)
from services import access


def scenario_shifted_short_rungs_and_exhausted_ladders_keep_the_next_log():
    # Includes a shift onto a one-session rung before its old clock advances,
    # and a backward shift after the natural ladder has been exhausted.
    for shift in (-3, -1, 0, 1, 2, 4):
        for logged in (0, 1, 2, 4, 6, 8):
            _fresh()
            rid = _legacy(shift=shift, logged=logged)
            before = storage.get_program(rid)
            here, following = _legacy_rung(before), _legacy_rung(_with_one_more(before))
            _migrate()
            check(_current_title(rid) == here, f'{shift=} {logged=}: initial bookmark')
            check(programs.log_session(rid)['status'] == 'success', 'real session entry point ran')
            check(_current_title(rid) == following,
                  f'{shift=} {logged=}: wanted {following}, got {_current_title(rid)}')


def scenario_closed_runs_birthdate_fallback_and_phase_only_hand_scripts():
    _fresh()
    ids = []
    for member_id, state, birthdate in (('kid', 'done', ''), ('mom', 'dropped', 'not-a-date'),
                                       ('dad', 'dropped', None)):
        member = storage.get_member(member_id)
        storage.members_table.update({'birthdate': birthdate, 'stage_override': 'copilot'},
                                     storage.Query().id == member['id'])
        rid = _legacy(member_id, shift=0)
        row = storage.get_program(rid)
        phase = {'name': 'Time only', 'weeks': 9, 'milestone': 'Ready', 'steps': [],
                 'milestone_hit_at': row['created_at'] if state == 'done' else None,
                 'rotation': [{'label': 'Empty', 'steps': []},
                              {'label': 'Keep', 'steps': ['Practise gently']}]}
        storage.update_program(rid, {'state': state, 'created_by': None, 'phases': [phase]})
        _legacy_script(rid, 'Time only', 0, 'Keep', 'My handwritten lesson', edited=True)
        old_script = dict(storage.program_lessons_table.all()[-1])
        ids.append((rid, row, old_script))
        if birthdate is None:
            storage.members_table.remove(storage.Query().id == member_id)
    check(storage.get_member('kid')['birthdate'] == '' and storage.get_member('mom')['birthdate'] == 'not-a-date'
          and storage.get_member('dad') is None, 'missing, invalid and deleted members are independent fixtures')
    check(_migrate() == 3, 'finished and dropped rows are all converted, including the deleted member')
    for rid, before, old_script in ids:
        run, curriculum = storage.get_program(rid), _library_of(rid)
        check(run['state'] in ('done', 'dropped') and run['emissions'] == before['emissions'],
              'closed state and emissions stay intact')
        check(curriculum['made_for']['age_band'] == 'any' and curriculum['created_by'] == run['member_id'],
              'missing/invalid birthdate ignores pinned stage; creator falls back to member')
        check(len(curriculum['lessons']) == 1, 'zero-unit phase gets one lesson')
        lesson = curriculum['lessons'][0]
        check(lesson['steps'] == [] and lesson['variants'] == [{'label': 'Keep', 'steps': ['Practise gently']}],
              'content-less base and step-less rotation filtering survive')
        script = storage.get_program_lesson(rid, {'lesson_id': lesson['id'], 'variant_label': 'Keep'})
        expected = {k: v for k, v in old_script.items() if k not in ('phase_name', 'unit_n', 'session_label')}
        check(script == {**expected, 'lesson_id': lesson['id'], 'variant_label': 'Keep'},
              'phase-only zero slot rekeys without touching hand edits, timestamps or scene data')
        check(all(k not in run for k in ('title', 'source', 'phases')) and run['starting_point'] == 'never played',
              'curriculum leaves the raw run; private input stays')
        check((run['progress']['current'] is None) == (run['state'] == 'done'),
              'all judged phases have no current lesson; an unjudged dropped run keeps its bookmark')


def scenario_a_bad_first_row_rolls_back_without_blocking_later_rows_or_retries():
    _fresh()
    bad = _legacy(title='Bad first')
    _legacy_script(bad, 'Renamed phase', 2, '', 'Keep this hand edit', edited=True)
    good = _legacy(title='Good second')
    before = json.dumps(storage.get_program(bad), sort_keys=True)
    scripts = json.dumps(storage.program_lessons_table.all(), sort_keys=True)
    with patch.object(migrations.logger, 'exception') as errors, patch.object(migrations.logger, 'error') as summary:
        check(_migrate() == 1, 'the good row still converts after the bad row rolls back')
        check(_migrate() == 0, 'retry leaves the bad row alone and skips the converted row')
    check(errors.call_count == 2 and all(bad in str(call) for call in errors.call_args_list),
          'each failed attempt logs the bad run id with exception context')
    check(summary.call_count == 2 and all(bad in str(call) for call in summary.call_args_list),
          'each attempt summarizes the failed ids')
    check(json.dumps(storage.get_program(bad), sort_keys=True) == before
          and not storage.get_program(bad).get('library_id'), 'bad row stays unmarked and byte-identical')
    check(json.dumps(storage.program_lessons_table.all(), sort_keys=True) == scripts,
          'the orphan hand edit stays byte-identical on its old key')
    check(len(storage.get_library_programs()) == 1 and storage.get_program(good).get('library_id'),
          'only the good row has a library, including after retry')


def scenario_missing_curriculum_and_gone_runs_are_skipped():
    _fresh()
    blank = programs.create_row({'member_id': 'kid'})
    marked = _legacy(title='Marked deleting')
    storage.programs_table.update({'deleting': 'pending'}, storage.Query().id == marked)
    ledger = _legacy(title='In an open project deletion')
    storage.add_deletion({'state': 'started', 'closure': [
        ['project', storage.get_program(ledger)['project_id']], ['program', ledger]]})
    check(access.gone('program', storage.get_program(marked))
          and access.gone('program', storage.get_program(ledger)), 'both gone paths are real')
    before = {rid: storage.get_program(rid) for rid in (blank, marked, ledger)}
    with patch.object(migrations.logger, 'exception') as errors:
        check(_migrate() == 0, 'nonlegacy and gone runs produce no library rows')
        check(not errors.called, 'skipped rows are not reported as failed conversions')
    check(not storage.get_library_programs() and before == {rid: storage.get_program(rid) for rid in before},
          'every skipped row stays unchanged, without publishing deleted curriculum')


def scenario_handwritten_units_support_zero_and_ordinal_script_keys():
    _fresh()
    rid, ordinal = _legacy(), _legacy()
    phases = [{'name': 'Handwritten', 'weeks': 1, 'steps': [], 'units': [
        {'title': 'Without n', 'sessions': 1, 'body': 'My lesson'},
        {'n': 3, 'title': 'Explicit three', 'sessions': 1},
        {'title': 'Another without n', 'sessions': 1}]}]
    for run_id in (rid, ordinal):
        storage.update_program(run_id, {'phases': phases})
    _legacy_script(rid, 'Handwritten', 0, '', 'Zero script', edited=True)
    _legacy_script(rid, 'Handwritten', 3, '', 'Explicit script')
    _legacy_script(ordinal, 'Handwritten', 2, '', 'Ordinal script')
    check(_migrate() == 2, 'missing n does not abort handwritten curriculum conversion')
    for run_id, number, words, edited in ((rid, 0, 'Zero script', True),
                                         (ordinal, 1, 'Ordinal script', False),
                                         (rid, 1, 'Explicit script', False)):
        lesson = _library_of(run_id)['lessons'][number]
        script = storage.get_program_lesson(run_id, {'lesson_id': lesson['id'], 'variant_label': ''})
        check(script and script['scenes'][0]['text'] == words and script['edited'] == edited,
              f'{words}: old zero/explicit keys and ordinal fallback never overwrite an existing mapping')


def scenario_startup_runner_reaches_conversion_after_the_audience_migrations():
    _fresh()
    rid = _legacy()
    calls = []
    real = migrations.migrate_program_library_v2499

    def convert():
        calls.append('migrate_program_library_v2499')
        return real()

    replacements = {}
    for name, fn in vars(migrations).items():
        if name.startswith('migrate_') and callable(fn):
            replacements[name] = (AsyncMock() if inspect.iscoroutinefunction(fn)
                                  else Mock(side_effect=lambda name=name: calls.append(name)))
    replacements['migrate_program_library_v2499'] = convert
    with patch.multiple(migrations, **replacements), patch.object(migrations.asyncio, 'sleep', new=AsyncMock()):
        asyncio.run(migrations.run_all_migrations())
    check(calls[-1] == 'migrate_program_library_v2499', 'conversion is registered last')
    check(calls.index('migrate_project_audiences_v2499') < len(calls) - 1,
          'project audience conversion precedes library conversion')
    check(storage.get_program(rid).get('library_id'), 'startup runner executed the real conversion')


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
    print(f'{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed')
    raise SystemExit(bool(failed))
