"""Family vitals: levels measured against this family's OWN baseline.

The pulse's whole claim is that the meaning lives in the derivative, so these
scenarios care about deltas, run lengths, and honest silence when there is not
yet enough history to say anything.
"""
import datetime
from harness import check
from services import storage, vitals


def _day(offset):
    return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()


def _reset():
    storage.daily_stats_table.truncate()
    storage.household_tasks_table.truncate()
    storage.routine_checks_table.truncate()


def _sched(events, assignments=None):
    return {'events': events, 'assignments': assignments or {},
            'ghost_assignments': {}, 'scheduled_errands': [], 'matched_rules': {}}


def _seed(date_str, *, load=None, margin=None, done=0, missed=0,
          first_hour=8, empty_evening=False, unassigned=0, canceled=0):
    """One day's vitals row, written the way record_daily_stats will."""
    storage.upsert_daily_stats(date_str, {
        'date': date_str,
        'drivers': {}, 'kids': {},
        'vitals': {
            'load': load or {},
            'margin_mins': 240 if margin is None else margin,
            'follow_through': {'done': done, 'missed': missed},
            'rest': {'first_hour': first_hour, 'empty_evening': empty_evening},
            'friction': {'unassigned': unassigned, 'canceled': canceled},
        }})


# --------------------------------------------------------------- measure_day

def scenario_margin_counts_committed_time():
    _reset()
    d = _day(0)
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: _sched([
            {'id': 'a', 'title': 'Practice', 'start': f'{d}T17:00:00', 'end': f'{d}T18:30:00'},
            {'id': 'b', 'title': 'Dentist', 'start': f'{d}T09:00:00', 'end': f'{d}T10:00:00'},
        ])
        row = vitals.measure_day(d)
        # 07:00-22:00 waking = 900 mins, minus 150 committed
        check(row['margin_mins'] == 750,
              f"margin is waking minutes less committed, got {row['margin_mins']}")
    finally:
        storage.get_cached_schedule = orig


def scenario_friction_sees_unassigned_and_canceled():
    _reset()
    d = _day(0)
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: _sched([
            {'id': 'a', 'title': 'Practice', 'start': f'{d}T17:00:00', 'end': f'{d}T18:00:00'},
            {'id': 'b', 'title': 'Game', 'start': f'{d}T19:00:00', 'end': f'{d}T20:00:00'},
            {'id': 'c', 'title': 'CANCELED: Piano', 'start': f'{d}T15:00:00', 'end': f'{d}T16:00:00'},
        ], assignments={'a': 'drv1'})
        row = vitals.measure_day(d)
        check(row['friction']['unassigned'] == 1,
              f"one ride reached its day with nobody on it, got {row['friction']}")
        check(row['friction']['canceled'] == 1,
              f"a canceled title counts as friction, got {row['friction']}")
    finally:
        storage.get_cached_schedule = orig


def scenario_rest_notices_an_empty_evening():
    _reset()
    d = _day(0)
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: _sched([
            {'id': 'a', 'title': 'Dentist', 'start': f'{d}T09:00:00', 'end': f'{d}T10:00:00'}])
        row = vitals.measure_day(d)
        check(row['rest']['empty_evening'] is True,
              "nothing after 17:00 is an empty evening")
        check(row['rest']['first_hour'] == 9, f"got {row['rest']}")
    finally:
        storage.get_cached_schedule = orig


def scenario_load_counts_doing_not_just_driving():
    _reset()
    d = _day(0)
    storage.household_tasks_table.insert({
        'id': 't1', 'title': 'Bins', 'status': 'done', 'completed_by': 'm1',
        'completed_at': datetime.datetime.fromisoformat(f'{d}T10:00:00').timestamp()})
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: _sched([])
        row = vitals.measure_day(d)
        check(row['load'].get('m1') == vitals.TASK_MINUTES,
              f"a finished task is load even with no driving, got {row['load']}")
    finally:
        storage.get_cached_schedule = orig


# --------------------------------------------------------------------- read

def scenario_thin_history_reports_levels_only():
    _reset()
    for i in range(5):
        _seed(_day(-i), margin=300)
    res = vitals.read()
    check(res['ready'] is False, f"five days is not a baseline, got {res['ready']}")
    check(res['days'] == 5, f"got {res['days']}")
    marg = [v for v in res['household'] if v['name'] == 'margin'][0]
    check(marg['current'] is not None and marg['delta_pct'] is None,
          "thin history reports a level and refuses a delta")


def scenario_delta_and_run_length():
    _reset()
    # 8 weeks of calm, then a hard fortnight: margin halves.
    for i in range(14, 56):
        _seed(_day(-i), margin=600)
    for i in range(0, 14):
        _seed(_day(-i), margin=300)
    res = vitals.read()
    check(res['ready'] is True, f"56 days is a baseline, got {res}")
    marg = [v for v in res['household'] if v['name'] == 'margin'][0]
    check(marg['delta_pct'] == -50,
          f"margin halved against its own baseline, got {marg['delta_pct']}")
    check(marg['direction'] == 'down', f"got {marg['direction']}")
    check(marg['run_days'] == 14,
          f"the run is how long it has been off baseline, got {marg['run_days']}")


def scenario_per_person_load_uses_their_own_baseline():
    _reset()
    # Jeff drives a lot and always has; Lorena's load has just doubled.
    for i in range(14, 56):
        _seed(_day(-i), load={'jeff': 200, 'lorena': 50})
    for i in range(0, 14):
        _seed(_day(-i), load={'jeff': 200, 'lorena': 100})
    res = vitals.read()
    people = {p['member_id']: p for p in res['people']}
    check(people['jeff']['delta_pct'] == 0,
          f"a heavy but steady load is not a finding, got {people['jeff']}")
    check(people['lorena']['delta_pct'] == 100,
          f"doubling against her own baseline is, got {people['lorena']}")


def scenario_days_since_an_empty_evening():
    _reset()
    for i in range(0, 30):
        _seed(_day(-i), empty_evening=(i >= 12))
    res = vitals.read()
    check(res['streaks']['days_since_empty_evening'] == 12,
          f"got {res['streaks']}")


# ---------------------------------------------------------- snapshot section

def scenario_snapshot_names_the_trend_not_the_number():
    _reset()
    for i in range(14, 56):
        _seed(_day(-i), margin=600, load={'lorena': 50})
    for i in range(0, 14):
        _seed(_day(-i), margin=300, load={'lorena': 100})
    text = vitals.snapshot_section()
    check('margin' in text.lower(), f"got:\n{text}")
    check('%' in text and '14 days' in text,
          f"a trend carries its size and its run, got:\n{text}")
    check('600' not in text, "the raw baseline number is noise for the Mind")


def scenario_snapshot_is_silent_without_history():
    _reset()
    check(vitals.snapshot_section() == '',
          "no history means no section — the Mind must not reason on nothing")


# ------------------------------------------------------- the wire, for real

def scenario_the_mind_actually_reads_the_pulse():
    """Entry points swallow exceptions, so run the real snapshot builder."""
    from services import mind
    _reset()
    for i in range(14, 56):
        _seed(_day(-i), margin=600)
    for i in range(0, 14):
        _seed(_day(-i), margin=300)
    text = mind.snapshot(datetime.datetime.now())
    check('FAMILY VITALS' in text, f"the section reaches the Mind's snapshot:\n{text[:400]}")
    check('margin down 50%' in text, f"with the trend in it:\n{text[:400]}")
    # And it must move the hash, or a worsening week never wakes a think.
    h1 = mind.snapshot_hash(text)
    for i in range(0, 14):
        _seed(_day(-i), margin=120)
    h2 = mind.snapshot_hash(mind.snapshot(datetime.datetime.now()))
    check(h1 != h2, "a changed pulse changes the snapshot hash")


def scenario_nightly_job_writes_vitals():
    """record_daily_stats is the only writer — prove the field lands."""
    from services import family_digest
    _reset()
    d = _day(0)
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: _sched([
            {'id': 'a', 'title': 'Practice', 'start': f'{d}T17:00:00',
             'end': f'{d}T18:00:00'}])
        row = family_digest.record_daily_stats(d)
        check('vitals' in row and row['vitals']['margin_mins'] == 840,
              f"the nightly row carries the day's pulse, got {row.get('vitals')}")
        stored = storage.get_daily_stats([d])
        check(stored and stored[0].get('vitals'), "and it persisted")
    finally:
        storage.get_cached_schedule = orig


if __name__ == '__main__':
    scenario_margin_counts_committed_time()
    scenario_friction_sees_unassigned_and_canceled()
    scenario_rest_notices_an_empty_evening()
    scenario_load_counts_doing_not_just_driving()
    scenario_thin_history_reports_levels_only()
    scenario_delta_and_run_length()
    scenario_per_person_load_uses_their_own_baseline()
    scenario_days_since_an_empty_evening()
    scenario_snapshot_names_the_trend_not_the_number()
    scenario_snapshot_is_silent_without_history()
    scenario_the_mind_actually_reads_the_pulse()
    scenario_nightly_job_writes_vitals()
    print("test_vitals OK")
