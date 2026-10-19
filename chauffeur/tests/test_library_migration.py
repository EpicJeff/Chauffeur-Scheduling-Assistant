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


def scenario_migration_residual_position():
    """Review Focus 4: mid-ladder with unit_shift and a rotation."""
    _fresh()
    rid = _legacy('kid', shift=1, logged=1)        # the walk says rung 2; the hand moved it on to rung 3
    before = storage.get_program(rid)
    here = _legacy_rung(before)
    next_one = _legacy_rung(_with_one_more(before))
    today = datetime.date.today()
    dates = [today + datetime.timedelta(days=n) for n in range(1, 15)
             if (today + datetime.timedelta(days=n)).weekday() in (0, 3)][:4]
    labels = [_legacy_label(before, d) for d in dates]
    check(here == 'F and G' and len(set(labels)) == 2, f'the oracle: {here} {labels}')
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
          f'the next session after conversion lands exactly where it would have: want {next_one}, got {_current_title(rid)}')


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


def scenario_a_crash_before_the_mark_converts_again_from_scratch():
    _fresh()
    rid = _legacy('kid')
    _legacy_script(rid, 'Foundations', 3, 'Session A', 'Rung three, session A')
    want = _legacy_rung(storage.get_program(rid))
    real = storage.add_library_program
    calls = []

    def crash_after_insert(row):
        calls.append(real(row))
        raise RuntimeError('the power went out before the mark')
    with patch.object(storage, 'add_library_program', side_effect=crash_after_insert):
        try:
            _migrate()
        except RuntimeError:
            pass
    check(calls, 'the crash was injected inside the conversion')
    check(not storage.get_program(rid).get('library_id'), 'unmarked: the row was not converted')
    _migrate()
    rows = storage.get_library_programs()
    check(len(rows) == 1, f'converted again from scratch, still one library row: {[r["id"] for r in rows]}')
    check(storage.get_program(rid)['library_id'] == rows[0]['id'], 'bound to it')
    check(len([r for r in storage.program_lessons_table.all() if r.get('program_id') == rid]) == 1, 'its script, once')
    check(_current_title(rid) == want, f'and the position the ladder had: want {want}, got {_current_title(rid)}')


def scenario_a_crash_after_the_mark_never_reconverts():
    _fresh()
    rid = _legacy('kid')
    _migrate()
    lid = storage.get_program(rid)['library_id']
    programs.log_session(rid)                     # life goes on after the mark
    progressed = json.loads(json.dumps(storage.get_program(rid)['progress']))
    library = json.loads(json.dumps(storage.get_library_program(lid)))
    calls = []

    def must_not(row):
        calls.append(row)
        raise AssertionError('a marked row must never convert again')
    with patch.object(storage, 'add_library_program', side_effect=must_not):
        try:
            _migrate()
        except AssertionError:
            pass
    check(not calls, f'the marked row is never converted again: {len(calls)} attempts')
    check(storage.get_program(rid)['library_id'] == lid and storage.get_program(rid)['progress'] == progressed,
          'its binding and progress are left alone')
    _migrate()
    check(storage.get_library_program(lid) == library and len(storage.get_library_programs()) == 1, 'idempotent')


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
