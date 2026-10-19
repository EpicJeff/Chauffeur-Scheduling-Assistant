"""Additional persisted-data edges; the seven-scenario migration contract is unchanged."""
import asyncio
import inspect
import traceback
from unittest.mock import AsyncMock, Mock, patch

from test_library_migration import (
    check, storage, programs, migrations, _fresh, _legacy, _legacy_script, _migrate,
    _legacy_rung, _with_one_more, _current_title, _library_of,
)


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
    for state, birthdate in (('done', ''), ('dropped', 'not-a-date')):
        member = storage.get_member('kid')
        storage.members_table.update({'birthdate': birthdate, 'stage_override': 'copilot'},
                                     storage.Query().id == member['id'])
        rid = _legacy(shift=0)
        row = storage.get_program(rid)
        phase = {'name': 'Time only', 'weeks': 9, 'milestone': 'Ready', 'steps': [],
                 'milestone_hit_at': row['created_at'] if state == 'done' else None,
                 'rotation': [{'label': 'Empty', 'steps': []},
                              {'label': 'Keep', 'steps': ['Practise gently']}]}
        storage.update_program(rid, {'state': state, 'created_by': None, 'phases': [phase]})
        _legacy_script(rid, 'Time only', 0, 'Keep', 'My handwritten lesson', edited=True)
        old_script = dict(storage.program_lessons_table.all()[-1])
        ids.append((rid, row, old_script))
    check(_migrate() == 2, 'finished and dropped rows are both converted')
    for rid, before, old_script in ids:
        run, curriculum = storage.get_program(rid), _library_of(rid)
        check(run['state'] in ('done', 'dropped') and run['emissions'] == before['emissions'],
              'closed state and emissions stay intact')
        check(curriculum['made_for']['age_band'] == 'any' and curriculum['created_by'] == 'kid',
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
