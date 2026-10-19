"""Program library, the migration (spec 2026-10-19-program-library-design.md rev 3, section 4; plan Task 1 Step 4).

`migrations.migrate_program_library_v2499()` converts every pre-library program row, each inside one
storage transaction with `library_id` marked LAST:

  * one `library_programs` row per program row (never deduplicated by title): title and source
    copied; `made_for` {age_band from the member's birthdate else 'any', minutes and
    sessions_per_week from the shape, assumes ''}; phases get stable ids; one lesson per unit in
    phase order with the rotation's labels as its variants; a phase with steps and no units is one
    lesson carrying those steps;
  * the run keeps its id, shape, emissions, kit thread and commitments (approve is never called);
    `milestone_hit_at` and the phase weeks move into `progress.phases`;
  * progress comes from today's selection: `current` = the rung `unit_for` picks after
    `unit_shift`, every earlier lesson of the phase completed, the current lesson's `done_sessions`
    the residual count clamped to 0..sessions-1, judged phases fully completed. The test holds an
    oracle copied from today's `unit_for` / `_practice_windows` arithmetic, so the check stays
    honest after Task 3 rewrites those functions: the next session after conversion lands exactly
    where it would have before, and every date keeps its rotation variant;
  * legacy scripts keyed (phase_name, unit_n, session_label) are re-keyed to (lesson id,
    variant label), read back through the storage helpers with the slot {'lesson_id',
    'variant_label'};
  * a crash before the mark converts the row again from scratch (still one library row); after the
    mark it is never converted again; the whole migration is idempotent.

Review Focus 4: scenario_migration_residual_position.

Run from chauffeur/:  python tests/test_library_migration.py   (HA_BASE_URL unset)
"""
import datetime
import json
import re
import time
import traceback
import uuid
from unittest.mock import patch

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)
from test_subjects import MOM, DAD, AUNT, KID
from services import storage, programs, projects, migrations

DAY = 86400
HEX = re.compile(r'[0-9a-f]{32}')
TABLES = ('programs_table', 'program_lessons_table', 'protected_commitments_table', 'projects_table',
          'members_table', 'threads_table', 'app_state_table', 'deletions_table')
UNITS = [('C position', 1), ('D and E', 2), ('F and G', 2), ('Hands together', 1), ('The whole scale', 1)]
ROTATION = [{'label': 'Session A', 'steps': ['Scales, slowly']}, {'label': 'Session B', 'steps': ['A short tune']}]


def _migrate():
    return migrations.migrate_program_library_v2499()


def _fresh():
    migrations.migrate_program_library_v2499    # the migration itself: red here until Task 5
    for name in TABLES:
        getattr(storage, name).truncate()
    table = getattr(storage, 'library_programs_table', None)
    if table is not None:
        table.truncate()
    for m in (MOM, DAD, AUNT, dict(KID, birthdate='2017-03-01')):
        storage.add_member(dict(m))


def _project(owner):
    res = projects.create({'title': f'{owner} music {uuid.uuid4().hex[:6]}', 'goal': 'g', 'done_when': 'd',
                           'owner_member_id': owner, 'audience': 'parents' if owner == 'kid' else 'private'}, dict(MOM))
    return res['project']


def _legacy(member='kid', title='Learn piano', shift=1, logged=1, shape=None):
    """A program row exactly as the pre-library code stored it, written past every new door."""
    now = time.time()
    rid = uuid.uuid4().hex
    project = _project(member)
    kit = storage.add_thread({'title': 'Get a keyboard stand', 'kind': 'project', 'owner_member_id': member,
                              'goal': 'Have what the next phase needs', 'created_by': 'mom', 'project_id': project['id']})
    sessions = ([{'minutes': 20, 'source': 'asked', 'note': '', 'ts': now - 45 * DAY} for _ in range(3)]
                + [{'minutes': 20, 'source': 'asked', 'note': '', 'ts': now - (20 - i) * DAY} for i in range(logged)])
    row = {
        'id': rid, 'member_id': member, 'title': title, 'state': 'active', 'created_by': 'mom',
        'project_id': project['id'], 'approved_by': 'mom', 'created_at': now - 60 * DAY,
        'starting_point': 'never played', 'paused_at': None, 'paused_slots': [], 'finished_at': None,
        'source': {'plan_name': 'Faber Piano Adventures', 'url': 'https://example.test/faber', 'why_this_one': '',
                   'facts': [], 'runners_up': [], 'answer': '', 'origin': 'cited', 'reason': '', 'hand_written': False},
        'shape': shape or {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': [0, 3], 'slots': []},
        'baseline': {'start_date': (datetime.date.today() - datetime.timedelta(days=60)).isoformat(), 'target_date': None,
                     'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0},
        'emissions': {'commitment_ids': [], 'thread_ids': [kit], 'event_ids': []},
        'sessions': sessions,
        'phases': [
            {'name': 'Warm-up', 'weeks': 2, 'what': 'Get comfortable', 'milestone': 'Sit and find middle C',
             'milestone_hit_at': now - 30 * DAY, 'steps': ['Sit tall', 'Find middle C']},
            {'name': 'Foundations', 'weeks': 7, 'what': 'Five-finger position', 'milestone': 'Play a C major scale',
             'milestone_hit_at': None, 'unit_shift': shift, 'steps': ['Warm up'], 'progression': 'One new note a week',
             'units': [{'n': i + 1, 'title': t, 'sessions': s, 'url': '', 'body': f'{t} notes'} for i, (t, s) in enumerate(UNITS)],
             'rotation': ROTATION},
            {'name': 'Songs', 'weeks': 4, 'what': 'Tunes', 'milestone': 'Play Ode to Joy', 'milestone_hit_at': None,
             'units': [{'n': 1, 'title': 'Ode to Joy, right hand', 'sessions': 2},
                       {'n': 2, 'title': 'Ode to Joy, both hands', 'sessions': 1}]}]}
    storage.programs_table.insert(row)
    projects.adopt('program', rid, None, project_id=project['id'])
    # A commitment is admitted only for a program that exists, so the windows come second.
    commitments = [storage.add_protected_commitment({
        'id': uuid.uuid4().hex, 'member_id': member, 'title': title, 'days_of_week': [d],
        'time_start': '17:00', 'time_end': '17:20', 'active': True, 'source': {'kind': 'program', 'id': rid}})
        for d in (0, 3)]
    check(all(commitments), 'the windows were admitted')
    storage.programs_table.update({'emissions': {**row['emissions'], 'commitment_ids': commitments}},
                                  storage.Query().id == rid)
    return rid


def _legacy_script(rid, phase, n, label, words, edited=False):
    storage.program_lessons_table.insert({
        'id': uuid.uuid4().hex, 'program_id': rid, 'phase_name': phase, 'unit_n': n, 'session_label': label,
        'origin': 'generated', 'source_url': '', 'edited': edited, 'scenes': [{'type': 'say', 'text': words}],
        'model': 'm', 'attempts': 0, 'note': '', 'created_at': time.time()})


# --- the oracle: today's arithmetic, copied so it outlives Task 3 ----------------------------

def _anchor(row):
    stamps = [p['milestone_hit_at'] for p in row['phases'] if p.get('milestone_hit_at')]
    if stamps:
        return datetime.datetime.fromtimestamp(max(stamps)).date()
    return datetime.date.fromisoformat(row['baseline']['start_date'])


def _since(row, anchor):
    return sum(1 for s in row['sessions'] if s.get('ts') is None
               or datetime.datetime.fromtimestamp(float(s['ts'])).date() >= anchor)


def _legacy_rung(row):
    """programs.unit_for as shipped before the library: the walk, then the hand on the ladder."""
    phase = next(p for p in row['phases'] if not p.get('milestone_hit_at'))
    units = phase['units']
    done, index, seen = _since(row, _anchor(row)), len(units) - 1, 0
    for i, unit in enumerate(units):
        seen += max(1, int(unit.get('sessions') or 1))
        if done < seen:
            index = i
            break
    index = max(0, min(len(units) - 1, index + int(phase.get('unit_shift') or 0)))
    return units[index]['title']


def _occurrences_before(days, anchor, day):
    span = (day - anchor).days
    if span <= 0:
        return 0
    total = 0
    for w in days:
        offset = (w - anchor.weekday()) % 7
        if offset < span:
            total += 1 + (span - 1 - offset) // 7
    return total


def _legacy_label(row, day):
    """programs._practice_windows' rotation deal for the one window on `day`."""
    commitments = [storage.get_protected_commitment(c) for c in row['emissions']['commitment_ids']]
    before = sum(_occurrences_before(set(c['days_of_week']), _anchor(row), day) for c in commitments)
    return ROTATION[before % len(ROTATION)]['label']


def _with_one_more(row):
    return {**row, 'sessions': row['sessions'] + [{'minutes': 20, 'source': 'added', 'note': '', 'ts': time.time()}]}


# --- reading the converted run ---------------------------------------------------------------

def _library_of(rid):
    return storage.get_library_program(storage.get_program(rid)['library_id'])


def _lesson(rid, title):
    return next(l for l in _library_of(rid)['lessons'] if l['title'] == title)


def _current_title(rid):
    current = (storage.get_program(rid).get('progress') or {}).get('current')
    return next((l['title'] for l in _library_of(rid)['lessons'] if l['id'] == current), None)


def _entry(rid, title):
    return ((storage.get_program(rid).get('progress') or {}).get('lessons') or {}).get(_lesson(rid, title)['id']) or {}


def _say_of(row):
    return json.dumps((row or {}).get('scenes'))


# --- scenarios -------------------------------------------------------------------------------

def scenario_one_library_row_per_program():
    _fresh()
    kate = _legacy('kid')
    mom = _legacy('mom', shape={'sessions_per_week': 3, 'minutes': 30, 'preferred_days': [], 'slots': []})
    _migrate()
    rows = storage.get_library_programs()
    check(len(rows) == 2, f'one library row per program, never merged by title: {[r["title"] for r in rows]}')
    for rid in (kate, mom):
        run = storage.get_program(rid)
        check(run and run.get('library_id') and storage.get_library_program(run['library_id']), f'{rid} is bound')
    k, m = _library_of(kate), _library_of(mom)
    check(k['id'] != m['id'], 'two rows, two ids')
    check(k['made_for'] == {'age_band': 'explorer', 'minutes': 20, 'sessions_per_week': 2, 'assumes': ''},
          f"Kate's profile from her birthdate and her shape: {k['made_for']}")
    check(m['made_for'] == {'age_band': 'any', 'minutes': 30, 'sessions_per_week': 3, 'assumes': ''},
          f"no birthdate on file: any: {m['made_for']}")
    check(k['title'] == 'Learn piano' and k['source']['plan_name'] == 'Faber Piano Adventures' and k['created_by'] == 'mom',
          f'title, source and maker copied: {k}')
    check('never played' not in json.dumps(k), 'the starting point stays on the run')
    check([p['name'] for p in k['phases']] == ['Warm-up', 'Foundations', 'Songs']
          and all(HEX.fullmatch(p['id']) for p in k['phases']), f'phases with stable ids: {k["phases"]}')
    phase = {p['name']: p['id'] for p in k['phases']}
    by_phase = {name: [l for l in k['lessons'] if l['phase_id'] == pid] for name, pid in phase.items()}
    check([l['title'] for l in k['lessons']] == ([l['title'] for l in by_phase['Warm-up']]
          + [t for t, _ in UNITS] + ['Ode to Joy, right hand', 'Ode to Joy, both hands']),
          f'one lesson per unit, in phase order: {[l["title"] for l in k["lessons"]]}')
    check(len(by_phase['Warm-up']) == 1 and by_phase['Warm-up'][0]['steps'] == ['Sit tall', 'Find middle C'],
          f'a phase with steps and no units is one lesson carrying them: {by_phase["Warm-up"]}')
    for lesson in by_phase['Foundations']:
        check([(v['label'], v['steps']) for v in lesson.get('variants') or []]
              == [('Session A', ['Scales, slowly']), ('Session B', ['A short tune'])],
              f'the rotation labels are the variants of each rung: {lesson}')
    check([int(l['sessions']) for l in by_phase['Foundations']] == [s for _, s in UNITS], 'each rung keeps its sessions')
    check(all(HEX.fullmatch(l['id']) for l in k['lessons']) and len({l['id'] for l in k['lessons']}) == len(k['lessons']),
          'every lesson has its own minted id')
    run = storage.get_program(kate)
    check(run['shape']['minutes'] == 20 and run['shape']['sessions_per_week'] == 2, f'the effective shape stays on the run: {run["shape"]}')
    loaded = programs.load(run)
    check(loaded['unresolved'] is False and [p['weeks'] for p in loaded['phases']] == [2, 7, 4],
          f"the run's pacing carried: {[p.get('weeks') for p in loaded['phases']]}")
    check(loaded['phases'][0].get('milestone_hit_at') and not loaded['phases'][1].get('milestone_hit_at'),
          'and its judgements')


def scenario_progress_comes_from_todays_position():
    _fresh()
    rid = _legacy('kid', shift=0, logged=4)        # 4 since the phase began: rung 3, one of its two sessions done
    before = storage.get_program(rid)
    check(_legacy_rung(before) == 'F and G', 'the oracle agrees with the arithmetic in this comment')
    _migrate()
    check(_current_title(rid) == 'F and G', f'current is today\'s rung: {storage.get_program(rid).get("progress")}')
    for title in ('C position', 'D and E'):
        check(_entry(rid, title).get('completed_at'), f'{title}: earlier rungs of the phase are completed')
    check(_entry(rid, 'F and G').get('done_sessions') == 1 and not _entry(rid, 'F and G').get('completed_at'),
          f"the residual count: {_entry(rid, 'F and G')}")
    warm = [l for l in _library_of(rid)['lessons'] if l['phase_id'] == _library_of(rid)['phases'][0]['id']][0]
    check(((storage.get_program(rid)['progress']['lessons'].get(warm['id'])) or {}).get('completed_at'),
          'a judged phase is fully completed')
    check(not _entry(rid, 'Ode to Joy, right hand').get('done_sessions'), 'the next phase is untouched')
    stamp = before['phases'][0]['milestone_hit_at']
    phases = storage.get_program(rid)['progress']['phases']
    check((phases.get(_library_of(rid)['phases'][0]['id']) or {}).get('milestone_hit_at') == stamp,
          f'the judgement moved onto the run as it was: {phases}')
    want = _legacy_rung(_with_one_more(before))
    programs.log_session(rid)
    check(want == 'Hands together' and _current_title(rid) == want,
          f'one more session lands where it would have before: want {want}, got {_current_title(rid)}')


def _parity(shift, logged, here_want, next_want):
    """Behavioural parity (controller ruling on spec §4 vs shipped unit_for): after conversion the
    bookmark is where the ladder was, every date keeps its variant, and the next logged session
    lands on the rung today's code reaches on an unconverted twin. How progress encodes that is
    the implementation's choice."""
    _fresh()
    rid = _legacy('kid', shift=shift, logged=logged)
    twin = json.loads(json.dumps(storage.get_program(rid)))      # the unconverted twin, held aside
    here = _legacy_rung(twin)
    next_one = _legacy_rung(_with_one_more(twin))
    today = datetime.date.today()
    dates = [today + datetime.timedelta(days=n) for n in range(1, 15)
             if (today + datetime.timedelta(days=n)).weekday() in (0, 3)][:4]
    labels = [_legacy_label(twin, d) for d in dates]
    check((here, next_one) == (here_want, next_want) and len(set(labels)) == 2,
          f'the oracle (shift {shift}, logged {logged}): {here} -> {next_one} {labels}')
    _migrate()
    check(_current_title(rid) == here, f'the bookmark is where the ladder was: want {here}, got {_current_title(rid)}')
    run = storage.get_program(rid)
    got = [programs.lesson_for(run, d) for d in dates]
    check([g['lesson_id'] for g in got] == [_lesson(rid, here)['id']] * len(dates)
          and [g['variant_label'] for g in got] == labels,
          f'every date keeps its rotation variant: want {labels}, got {[g["variant_label"] for g in got]}')
    check([g['steps'] for g in got] == [{'Session A': ['Scales, slowly'], 'Session B': ['A short tune']}[l] for l in labels],
          'with the variant\'s steps')
    programs.log_session(rid)
    check(_current_title(rid) == next_one,
          f'shift {shift}, logged {logged}: the next session lands where it would have: want {next_one}, got {_current_title(rid)}')


def scenario_migration_residual_position():
    """Review Focus 4: mid-ladder with unit_shift and a rotation, including the shifted boundary."""
    _parity(shift=1, logged=1, here_want='F and G', next_want='F and G')       # the hand moved it on; the next log stays
    _parity(shift=1, logged=2, here_want='F and G', next_want='Hands together')  # the boundary: the next log moves on


def scenario_scripts_are_rekeyed_per_variant():
    _fresh()
    rid = _legacy('kid')
    _legacy_script(rid, 'Foundations', 3, 'Session A', 'Rung three, session A')
    _legacy_script(rid, 'Foundations', 3, 'Session B', 'Rung three, session B', edited=True)
    _legacy_script(rid, 'Songs', 1, '', 'Right hand only')
    _migrate()
    three = _lesson(rid, 'F and G')['id']
    a = storage.get_program_lesson(rid, {'lesson_id': three, 'variant_label': 'Session A'})
    b = storage.get_program_lesson(rid, {'lesson_id': three, 'variant_label': 'Session B'})
    song = storage.get_program_lesson(rid, {'lesson_id': _lesson(rid, 'Ode to Joy, right hand')['id'], 'variant_label': ''})
    check('Rung three, session A' in _say_of(a) and 'Rung three, session B' in _say_of(b) and 'Right hand only' in _say_of(song),
          f'each script under its lesson and variant: {a} {b} {song}')
    check(b.get('edited') is True and not a.get('edited'), 'a hand edit stays a hand edit')
    check(storage.get_program_lesson(rid, {'lesson_id': _lesson(rid, 'D and E')['id'], 'variant_label': 'Session A'}) is None,
          'nothing lands on a rung that had no script')
    check(len([r for r in storage.program_lessons_table.all() if r.get('program_id') == rid]) == 3,
          'three scripts before, three after')


def _raw_run(rid):
    return json.loads(json.dumps(storage.get_program(rid)))


def _raw_scripts(rid):
    return sorted(json.dumps(r, sort_keys=True) for r in storage.program_lessons_table.all() if r.get('program_id') == rid)


class _WritesFail:
    """The scripts table, with every write refused: a crash while the scripts are being re-keyed."""
    WRITES = ('insert', 'insert_multiple', 'update', 'update_multiple', 'upsert', 'remove', 'truncate')

    def __init__(self, table):
        self._table, self.hits = table, 0

    def __getattr__(self, name):
        if name in self.WRITES:
            def fail(*a, **k):
                self.hits += 1
                raise RuntimeError('the disk filled while the scripts were moving')
            return fail
        return getattr(self._table, name)

    def __len__(self):
        return len(self._table)


class _MarkFails:
    """The programs table, with the write that sets `library_id` (the mark) failing: before it is
    applied (`after=False`) or just after it was applied, before anything could commit (`after=True`).
    Every other read and write passes through."""
    WRITES = ('insert', 'insert_multiple', 'update', 'update_multiple', 'upsert')

    def __init__(self, table, after=False):
        self._table, self._after, self.hits = table, after, 0

    def __getattr__(self, name):
        attr = getattr(self._table, name)
        if name not in self.WRITES:
            return attr

        def write(*a, **k):
            fields = a[0] if a else k.get('fields') or k.get('document') or {}
            marks = isinstance(fields, dict) and fields.get('library_id')
            if marks and not self._after:
                self.hits += 1
                raise RuntimeError('the power went out writing the mark')
            out = attr(*a, **k)
            if marks:
                self.hits += 1
                raise RuntimeError('the power went out just after the mark')
            return out
        return write

    def __len__(self):
        return len(self._table)


def _crash(during):
    """Run the migration through one injected crash; the process 'dies' there (the error is eaten)."""
    try:
        with during:
            _migrate()
    except RuntimeError:
        pass


def scenario_a_crash_before_the_mark_converts_again_from_scratch():
    _fresh()
    rid = _legacy('kid')
    _legacy_script(rid, 'Foundations', 3, 'Session A', 'Rung three, session A')
    want = _legacy_rung(storage.get_program(rid))
    run_before, scripts_before = _raw_run(rid), _raw_scripts(rid)
    real = storage.add_library_program
    calls = []

    def crash_after_insert(row):
        calls.append(real(row))
        raise RuntimeError('the power went out before the mark')
    _crash(patch.object(storage, 'add_library_program', side_effect=crash_after_insert))
    check(calls, 'the crash was injected inside the conversion, after the library row was written')
    check(storage.get_library_programs() == [], f'rolled back: no library row survives: {storage.get_library_programs()}')
    check(_raw_run(rid) == run_before and _raw_scripts(rid) == scripts_before,
          'the run and its scripts are exactly as they were: unmarked, unconverted')
    proxy = _WritesFail(storage.program_lessons_table)
    _crash(patch.object(storage, 'program_lessons_table', proxy))
    check(proxy.hits, 'the crash was injected while the scripts were being re-keyed')
    check(storage.get_library_programs() == [] and _raw_run(rid) == run_before and _raw_scripts(rid) == scripts_before,
          'rolled back again: no library row, the run unmarked, the scripts untouched')
    mark = _MarkFails(storage.programs_table)
    _crash(patch.object(storage, 'programs_table', mark))
    check(mark.hits, 'the crash was injected on the final write, the library_id mark itself')
    check(storage.get_library_programs() == [], f'a failed mark leaves no library row: {storage.get_library_programs()}')
    run_now = _raw_run(rid)
    check(not run_now.get('library_id') and not run_now.get('progress') and run_now == run_before,
          f'nor any progress or other change on the run: {run_now}')
    check(_raw_scripts(rid) == scripts_before, 'and the scripts are still on the legacy key')
    _migrate()
    rows = storage.get_library_programs()
    check(len(rows) == 1, f'converted from scratch, one library row: {[r["id"] for r in rows]}')
    check(storage.get_program(rid)['library_id'] == rows[0]['id'], 'bound to it')
    check(len([r for r in storage.program_lessons_table.all() if r.get('program_id') == rid]) == 1, 'its script, once')
    check(_current_title(rid) == want, f'and the position the ladder had: want {want}, got {_current_title(rid)}')


def scenario_a_crash_after_the_mark_never_reconverts():
    _fresh()
    first, second = _legacy('kid'), _legacy('mom')
    for rid in (first, second):
        _legacy_script(rid, 'Foundations', 3, 'Session A', 'Rung three, session A')
    before = {rid: (_raw_run(rid), _raw_scripts(rid)) for rid in (first, second)}
    real = storage.add_library_program
    calls = []

    def second_row_crashes(row):
        calls.append(row)
        if len(calls) == 2:
            raise RuntimeError('the power went out on the next program')
        return real(row)
    _crash(patch.object(storage, 'add_library_program', side_effect=second_row_crashes))
    check(len(calls) == 2, f'one row converted, the crash on the next: {len(calls)}')
    marked = [rid for rid in (first, second) if storage.get_program(rid).get('library_id')]
    check(len(marked) == 1 and len(storage.get_library_programs()) == 1, f'exactly one row marked: {marked}')
    done, other = marked[0], next(r for r in (first, second) if r != marked[0])
    lesson = _lesson(done, 'F and G')['id']
    check(storage.get_program_lesson(done, {'lesson_id': lesson, 'variant_label': 'Session A'})
          and (storage.get_program(done).get('progress') or {}).get('current'),
          'the marked row is completely converted: progress and re-keyed script')
    check((_raw_run(other), _raw_scripts(other)) == before[other], 'the crashed row is exactly as it was')
    progressed = json.loads(json.dumps(storage.get_program(done)['progress']))
    lid = storage.get_program(done)['library_id']
    calls.clear()
    with patch.object(storage, 'add_library_program', side_effect=lambda row: calls.append(row) or real(row)):
        _migrate()
    check(len(calls) == 1, f'the retry converts only the unmarked row: {len(calls)} conversions')
    check(storage.get_program(done)['library_id'] == lid and storage.get_program(done)['progress'] == progressed,
          'the marked row is never converted again')
    check(storage.get_program(other).get('library_id') and len(storage.get_library_programs()) == 2, 'and the other is now done')
    programs.log_session(done)                    # life goes on after the mark
    progressed = json.loads(json.dumps(storage.get_program(done)['progress']))
    library = json.loads(json.dumps(storage.get_library_program(lid)))
    calls.clear()
    with patch.object(storage, 'add_library_program', side_effect=lambda row: calls.append(row) or real(row)):
        _migrate()
    check(not calls and storage.get_program(done)['progress'] == progressed
          and storage.get_library_program(lid) == library and len(storage.get_library_programs()) == 2,
          'idempotent: nothing converts again and nothing is recomputed')
    # A crash right after a mark was written: that row is converted entirely or not at all.
    third = _legacy('kid', title='Learn the cello')
    _legacy_script(third, 'Foundations', 3, 'Session A', 'Rung three, session A')
    third_before = (_raw_run(third), _raw_scripts(third))
    mark = _MarkFails(storage.programs_table, after=True)
    _crash(patch.object(storage, 'programs_table', mark))
    check(mark.hits, 'the crash was injected just after a mark was written')
    cellos = [r for r in storage.get_library_programs() if r.get('title') == 'Learn the cello']
    if storage.get_program(third).get('library_id'):
        three = _lesson(third, 'F and G')['id']
        check(len(cellos) == 1 and _library_of(third)['id'] == cellos[0]['id']
              and (storage.get_program(third).get('progress') or {}).get('current')
              and storage.get_program_lesson(third, {'lesson_id': three, 'variant_label': 'Session A'}),
              'marked, so the conversion is complete: library row, progress, re-keyed script')
    else:
        check(not cellos and (_raw_run(third), _raw_scripts(third)) == third_before,
              'not marked, so nothing of the conversion remains')
    _migrate()
    cellos = [r for r in storage.get_library_programs() if r.get('title') == 'Learn the cello']
    check(storage.get_program(third).get('library_id') and len(cellos) == 1
          and storage.get_program(third)['library_id'] == cellos[0]['id'],
          'either way the retry leaves exactly one converted row')


def scenario_emissions_kit_thread_and_ids_are_untouched():
    _fresh()
    rid = _legacy('kid')
    before = storage.get_program(rid)
    kit = storage.get_thread(before['emissions']['thread_ids'][0])
    with patch.object(programs, 'approve', side_effect=AssertionError('conversion never calls approve')):
        _migrate()
    after = storage.get_program(rid)
    check(after is not None and after['id'] == rid, 'the run keeps its id')
    check(after['emissions'] == before['emissions'], f"emissions untouched: {after['emissions']}")
    check(after['state'] == 'active' and after['sessions'] == before['sessions'] and after['member_id'] == 'kid'
          and after['project_id'] == before['project_id'], 'state, log, person and project untouched')
    thread = storage.get_thread(kit['id'])
    check(thread and thread['project_id'] == kit['project_id'] and thread['owner_member_id'] == kit['owner_member_id'],
          'the kit thread keeps its project')
    live = [c for c in storage.get_protected_commitments(include_inactive=True) if c['id'] in before['emissions']['commitment_ids']]
    check(len(live) == 2 and all(c.get('active') for c in live), 'the commitments are still reserved')


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
