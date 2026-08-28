"""Goal progress as a vital sign — the only one that can measure a family
getting what it wanted rather than surviving what it was handed."""
import datetime
import time

from harness import check
from services import storage, vitals


def scenario_a_day_measures_sessions_per_member():
    storage.programs_table.truncate()
    pid = storage.add_program({'member_id': 'lily', 'title': 'Guitar',
                               'state': 'active'})
    storage.append_program_session(pid, {'ts': time.time(), 'minutes': 25,
                                         'source': 'asked'})
    day = vitals.measure_day(datetime.date.today().isoformat())
    check('progress' in day, f"the day carries a progress reading, got {sorted(day)}")
    check(day['progress'].get('lily') == 1,
          f"counting that person's sessions, got {day['progress']}")


def scenario_progress_is_worse_when_it_falls():
    check(vitals._WORSE_WHEN.get('progress') == 'down',
          "a family doing less of what it wanted is the bad direction")


def scenario_progress_is_per_member_not_a_household_score():
    check('progress' not in vitals.HOUSEHOLD_SIGNS,
          "progress is measured per person, like load — never as one family number")


def _rows(values):
    """A `daily_stats`-shaped history carrying one person's progress sign."""
    today = datetime.date.today()
    return [{'date': (today - datetime.timedelta(days=len(values) - 1 - i)).isoformat(),
             'vitals': {'progress': {'lily': v}, 'load': {'lily': v}}}
            for i, v in enumerate(values)]


def scenario_the_progress_sign_is_never_phrased_as_a_run():
    """The streak the banned-key screen could not see, because it lives in
    `daily_stats` rather than the program row: `vitals._reading` computed
    `run_days` from a per-day, per-person session count and `_phrase` printed
    it as "6 days running" about a child's practice. That is a streak, and
    the arc's first rule is that one exists nowhere."""
    series = [(f'd{i}', 0.0) for i in range(21)] + [(f'x{i}', 5.0) for i in range(7)]
    r = vitals._reading('progress', series, 'Lily — practice')
    check(r['run_days'] == 0,
          f"there is no run to render for progress, got {r}")
    phrase = vitals._phrase(r) or ''
    for claim in ('running', 'days in a row', 'day streak', 'consecutive'):
        check(claim not in phrase.lower(),
              f"and nothing phrases one, got {phrase!r}")
    load = vitals._reading('load', series, 'Lily')
    check(load['run_days'] > 0,
          f"the suppression is specific to progress, not a blanket, got {load}")


def scenario_the_two_person_signs_do_not_read_the_same():
    """Both `load` and `progress` ride `res['people']` and `_phrase` prints
    only the label -- with the member's name overwriting both, the Mind's
    snapshot got two indistinguishable bullets: one meaning Lily's load fell
    (good) and one meaning her practice did (not)."""
    storage.programs_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})
    rows = _rows([3.0] * 21 + [1.0] * 7)
    real = storage.get_daily_stats
    storage.get_daily_stats = lambda wanted: rows
    try:
        res = vitals.read()
    finally:
        storage.get_daily_stats = real
    labels = [r['label'] for r in res['people'] if r['member_id'] == 'lily']
    check(len(labels) == 2, f"one reading each, got {labels}")
    check(len(set(labels)) == 2,
          f"and they must not be the same sentence, got {labels}")
    check(any('practice' in lab for lab in labels),
          f"the progress one says which sign it is, got {labels}")


if __name__ == '__main__':
    scenario_a_day_measures_sessions_per_member()
    scenario_progress_is_worse_when_it_falls()
    scenario_progress_is_per_member_not_a_household_score()
    scenario_the_progress_sign_is_never_phrased_as_a_run()
    scenario_the_two_person_signs_do_not_read_the_same()
    print("test_programs_vitals OK")
