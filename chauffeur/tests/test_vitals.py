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
    storage.day_counters_table.truncate()


def _sched(events, assignments=None):
    return {'events': events, 'assignments': assignments or {},
            'ghost_assignments': {}, 'scheduled_errands': [], 'matched_rules': {}}


def _seed(date_str, *, load=None, margin=None, done=0, missed=0,
          first_hour=8, empty_evening=False, unassigned=0, canceled=0,
          nudges=0, late_overrides=0, coverage_asks=0,
          meals_together=1, car_meals=0, moments=0, parent_rides=0):
    """One day's vitals row, written the way record_daily_stats will."""
    storage.upsert_daily_stats(date_str, {
        'date': date_str,
        'drivers': {}, 'kids': {},
        'vitals': {
            'load': load or {},
            'margin_mins': 240 if margin is None else margin,
            'follow_through': {'done': done, 'missed': missed},
            'rest': {'first_hour': first_hour, 'empty_evening': empty_evening},
            'friction': {'unassigned': unassigned, 'canceled': canceled,
                         'arrival_nudge': nudges, 'late_override': late_overrides,
                         'coverage_ask': coverage_asks},
            'together': {'meals_together': meals_together, 'car_meals': car_meals,
                         'moments': moments, 'parent_rides': parent_rides},
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


def scenario_open_threads_are_load():
    _reset()
    from services import threads as _threads
    storage.threads_table.truncate()
    _threads.create('Pool', owner_member_id='m1')
    _threads.create('Gutters', owner_member_id='m1')
    d = _day(0)
    orig = storage.get_cached_schedule
    from services import meals as _meals
    orig_plan = _meals.eating_plan
    try:
        _meals.eating_plan = lambda *a, **k: {'sittings': []}
        storage.get_cached_schedule = lambda: _sched([])
        row = vitals.measure_day(d)
        check(row['load'].get('m1') == 2 * vitals.THREAD_MINUTES,
              f"the mental load of carrying loops is load, got {row['load']}")
    finally:
        storage.get_cached_schedule = orig
        _meals.eating_plan = orig_plan
        storage.threads_table.truncate()


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


# -------------------------------------------- together & the real friction

def scenario_together_counts_connection_not_calories():
    _reset()
    d = _day(0)
    orig_plan, orig_sched = None, storage.get_cached_schedule
    from services import meals as _meals, presence as _presence
    orig_plan = _meals.eating_plan
    orig_count = _presence.count_moments_since
    try:
        storage.get_cached_schedule = lambda: _sched([])
        _meals.eating_plan = lambda *a, **k: {'sittings': [
            {'where_kind': 'at_home', 'member_ids': ['m1', 'm2', 'm3']},
            {'where_kind': 'in_car', 'member_ids': ['m4']},
        ]}
        _presence.count_moments_since = lambda ts: 2
        row = vitals.measure_day(d)
        t = row['together']
        check(t['meals_together'] == 1, f"a shared sitting counts once, got {t}")
        check(t['car_meals'] == 1, f"a car sitting is counted apart, got {t}")
        check(t['moments'] == 2, f"got {t}")
    finally:
        storage.get_cached_schedule = orig_sched
        _meals.eating_plan = orig_plan
        _presence.count_moments_since = orig_count


def scenario_a_kid_riding_with_a_parent_is_togetherness():
    _reset()
    d = _day(0)
    # add_member returns a doc id and does NOT mint an 'id' field — a member
    # without one leaks into every later scenario and breaks anything that
    # reads m['id'], so build them the way the app does.
    storage.add_member({'id': 'vit_p', 'name': 'Jeff', 'role': 'parent',
                        'driver_id': 'vit_drv'})
    storage.add_member({'id': 'vit_k', 'name': 'Lily', 'role': 'child',
                        'passenger_id': 'vit_pax'})
    orig = storage.get_cached_schedule
    from services import meals as _meals
    orig_plan = _meals.eating_plan
    try:
        _meals.eating_plan = lambda *a, **k: {'sittings': []}
        storage.get_cached_schedule = lambda: _sched([
            {'id': 'e1', 'title': 'Practice', 'start': f'{d}T17:00:00',
             'end': f'{d}T18:00:00', 'attendees': ['vit_pax']}],
            assignments={'e1': 'vit_drv'})
        row = vitals.measure_day(d)
        check(row['together']['parent_rides'] == 1,
              f"car time with a parent is connection time, got {row['together']}")
    finally:
        storage.get_cached_schedule = orig
        _meals.eating_plan = orig_plan
        storage.delete_member('vit_p')
        storage.delete_member('vit_k')


def scenario_friction_folds_in_the_live_counters():
    _reset()
    d = _day(0)
    storage.bump_day_counter(d, 'arrival_nudge')
    storage.bump_day_counter(d, 'arrival_nudge')
    storage.bump_day_counter(d, 'late_override')
    orig = storage.get_cached_schedule
    from services import meals as _meals
    orig_plan = _meals.eating_plan
    try:
        _meals.eating_plan = lambda *a, **k: {'sittings': []}
        storage.get_cached_schedule = lambda: _sched([])
        row = vitals.measure_day(d)
        f = row['friction']
        check(f['arrival_nudge'] == 2 and f['late_override'] == 1,
              f"the day's live scrambles land in the row, got {f}")
    finally:
        storage.get_cached_schedule = orig
        _meals.eating_plan = orig_plan


def scenario_a_same_day_override_counts_a_tomorrow_one_does_not():
    """The counters are only worth anything if the real code paths bump them."""
    _reset()
    today, tomorrow = _day(0), _day(1)
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: _sched([
            {'id': 'ev_today', 'title': 'Practice', 'start': f'{today}T17:00:00',
             'end': f'{today}T18:00:00'},
            {'id': 'ev_tmrw', 'title': 'Game', 'start': f'{tomorrow}T17:00:00',
             'end': f'{tomorrow}T18:00:00'}])
        storage.add_override({'event_id': 'ev_tmrw', 'override_type': 'driver',
                              'driver_id': 'd1'})
        check(storage.get_day_counters(today).get('late_override') is None,
              "rearranging tomorrow is planning, not a scramble")
        storage.add_override({'event_id': 'ev_today', 'override_type': 'driver',
                              'driver_id': 'd1'})
        check(storage.get_day_counters(today).get('late_override') == 1,
              f"rearranging today is, got {storage.get_day_counters(today)}")
    finally:
        storage.get_cached_schedule = orig
        storage.overrides_table.truncate()


def scenario_friction_series_sums_every_kind():
    _reset()
    for i in range(14, 56):
        _seed(_day(-i), unassigned=0, nudges=0, late_overrides=0)
    for i in range(0, 14):
        _seed(_day(-i), unassigned=1, nudges=1, late_overrides=1)
    res = vitals.read()
    fr = [v for v in res['household'] if v['name'] == 'friction'][0]
    check(fr['current'] == 3.0,
          f"friction is every scramble kind, not just the proxy, got {fr}")
    check(fr['worse'] is True, "more friction is bad news")


def scenario_together_trends_and_reads_as_worse_when_falling():
    _reset()
    for i in range(14, 56):
        _seed(_day(-i), meals_together=2, moments=2)
    for i in range(0, 14):
        _seed(_day(-i), meals_together=1, moments=0)
    res = vitals.read()
    tg = [v for v in res['household'] if v['name'] == 'together'][0]
    check(tg['delta_pct'] == -75, f"got {tg['delta_pct']}")
    check(tg['worse'] is True, "less togetherness is the bad direction")


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
    scenario_open_threads_are_load()
    scenario_thin_history_reports_levels_only()
    scenario_delta_and_run_length()
    scenario_per_person_load_uses_their_own_baseline()
    scenario_days_since_an_empty_evening()
    scenario_snapshot_names_the_trend_not_the_number()
    scenario_snapshot_is_silent_without_history()
    scenario_together_counts_connection_not_calories()
    scenario_a_kid_riding_with_a_parent_is_togetherness()
    scenario_friction_folds_in_the_live_counters()
    scenario_a_same_day_override_counts_a_tomorrow_one_does_not()
    scenario_friction_series_sums_every_kind()
    scenario_together_trends_and_reads_as_worse_when_falling()
    scenario_the_mind_actually_reads_the_pulse()
    scenario_nightly_job_writes_vitals()
    print("test_vitals OK")
