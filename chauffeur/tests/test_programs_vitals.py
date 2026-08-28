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


if __name__ == '__main__':
    scenario_a_day_measures_sessions_per_member()
    scenario_progress_is_worse_when_it_falls()
    scenario_progress_is_per_member_not_a_household_score()
    print("test_programs_vitals OK")
