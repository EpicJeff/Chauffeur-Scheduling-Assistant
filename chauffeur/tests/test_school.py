"""Tests for school-calendar awareness (services/school.py).

Load-bearing properties: weekends are never school days; year bounds mark
summer out; a designated calendar's all-day no-school events (keyword-
matched, multi-day spans expanded, exclusive ends honored) mark days out;
timed events never close a school day; nothing configured = plain weekday
behavior; fetch failures fail OPEN; the bus launch honors the gate.

Run from chauffeur/:  python tests/test_school.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import bus, school, storage

TODAY = datetime.date.today()
MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())
TUESDAY = MONDAY + datetime.timedelta(days=1)
SATURDAY = MONDAY + datetime.timedelta(days=5)


def _settings(**kw):
    base = {"calendar_ids": ["primary"]}
    base.update(kw)
    storage.get_settings = lambda: base


def _gcal_events(events):
    """Mock the designated-calendar fetch with raw Google items."""
    from services import calendar as gcal
    return mock.patch.object(gcal, '_fetch_single_calendar',
                             return_value=('school', events))


def _all_day(title, start, end=None):
    e = {"summary": title, "start": {"date": start.isoformat()}, "end": {}}
    if end:
        e["end"] = {"date": end.isoformat()}
    return e


def scenario_unconfigured_is_plain_weekdays():
    school._reset_cache()
    _settings()
    check(school.school_in_session(MONDAY) is True, "weekday in session by default")
    check(school.school_in_session(SATURDAY) is False, "weekend never in session")


def scenario_year_bounds_mark_summer_out():
    school._reset_cache()
    _settings(school_year_start=(MONDAY - datetime.timedelta(days=30)).isoformat(),
              school_year_end=(MONDAY + datetime.timedelta(days=30)).isoformat())
    check(school.school_in_session(MONDAY) is True, "inside the school year")
    _settings(school_year_end=(MONDAY - datetime.timedelta(days=7)).isoformat())
    check(school.school_in_session(MONDAY) is False, "after the last day = summer")
    _settings(school_year_start=(MONDAY + datetime.timedelta(days=7)).isoformat())
    check(school.school_in_session(MONDAY) is False, "before the first day = summer")


def scenario_no_school_calendar_events():
    school._reset_cache()
    _settings(school_calendar_id="school")
    span_start, span_end = MONDAY, MONDAY + datetime.timedelta(days=2)  # Mon+Tue off
    events = [
        _all_day("No School — Fall Break", span_start, span_end),
        _all_day("Picture Day", MONDAY + datetime.timedelta(days=3)),  # not a closure
        {"summary": "No school assembly", "start": {"dateTime": "whatever"}},  # timed: ignored
    ]
    with _gcal_events(events):
        check(school.school_in_session(MONDAY) is False, "keyword all-day event closes the day")
        check(school.school_in_session(TUESDAY) is False, "multi-day span expands (exclusive end)")
        check(school.school_in_session(MONDAY + datetime.timedelta(days=2)) is True,
              "day after the span is back in session")
        check(school.school_in_session(MONDAY + datetime.timedelta(days=3)) is True,
              "non-matching all-day event does not close school")


def scenario_custom_keywords():
    school._reset_cache()
    _settings(school_calendar_id="school", school_closed_keywords="asueto")
    with _gcal_events([_all_day("Asueto escolar", MONDAY)]):
        check(school.school_in_session(MONDAY) is False, "custom keyword list honored")
    school._reset_cache()
    with _gcal_events([_all_day("No School", MONDAY)]):
        check(school.school_in_session(MONDAY) is True,
              "custom list replaces the default (no-school no longer matches)")


def scenario_fetch_failure_fails_open():
    school._reset_cache()
    _settings(school_calendar_id="school")
    from services import calendar as gcal
    with mock.patch.object(gcal, '_fetch_single_calendar', return_value=('school', None)):
        check(school.school_in_session(MONDAY) is True,
              "fetch failure with no cache fails OPEN")
    # A prior good cache keeps serving through later failures
    school._reset_cache()
    with _gcal_events([_all_day("No School", MONDAY)]):
        check(school.school_in_session(MONDAY) is False, "good fetch cached")
    with mock.patch.object(gcal, '_fetch_single_calendar', return_value=('school', None)):
        check(school.school_in_session(MONDAY) is False, "stale cache still answers")


def scenario_auto_year_bounds_from_markers():
    school._reset_cache()
    _settings(school_calendar_id="school")
    f1 = MONDAY - datetime.timedelta(days=98)
    l1 = MONDAY + datetime.timedelta(days=98)
    f2 = MONDAY + datetime.timedelta(days=168)
    events = [
        _all_day("First Day of School", f1),
        _all_day("Last Day of School", l1),
        # Some districts put the marker on a TIMED event — still a marker.
        {"summary": "First Day of School",
         "start": {"dateTime": datetime.datetime.combine(f2, datetime.time(8)).isoformat()},
         "end": {}},
    ]
    with _gcal_events(events):
        check(school.school_in_session(MONDAY) is True, "inside the detected year")
        summer = MONDAY + datetime.timedelta(days=126)
        check(school.school_in_session(summer) is False, "summer between years is out")
        check(school.school_in_session(MONDAY + datetime.timedelta(days=175)) is True,
              "next detected year (timed marker) back in session")
        check(school.school_in_session(f1 - datetime.timedelta(days=7)) is False,
              "before the first first-day is out")


def scenario_open_ended_year_and_manual_override():
    school._reset_cache()
    _settings(school_calendar_id="school")
    f = MONDAY - datetime.timedelta(days=14)
    with _gcal_events([_all_day("School Begins", f)]):
        check(school.school_in_session(MONDAY) is True,
              "first day with no last day yet: open-ended year in session")
        check(school.school_in_session(f + datetime.timedelta(days=336)) is False,
              "open-ended year still closes ~11 months out")
    # Setting either manual date disables auto-detection entirely.
    school._reset_cache()
    _settings(school_calendar_id="school",
              school_year_start=(MONDAY - datetime.timedelta(days=30)).isoformat())
    with _gcal_events([_all_day("First Day of School", MONDAY - datetime.timedelta(days=98)),
                       _all_day("Last Day of School", MONDAY + datetime.timedelta(days=98))]):
        check(school.school_in_session(MONDAY + datetime.timedelta(days=126)) is True,
              "manual bound set -> auto intervals ignored (parent took control)")


def scenario_bus_launch_honors_the_gate():
    school._reset_cache()
    _settings()
    kid = {"id": "k", "name": "Addison", "role": "child",
           "bus_am_stop_time": "07:22", "bus_walk_mins": 5}
    with mock.patch.object(bus, 'bus_active', return_value=False):
        check(bus.morning_launch(dict(kid), MONDAY.isoformat()) is not None,
              "bus line on a school day")
        with mock.patch.object(school, 'school_in_session', return_value=False):
            check(bus.morning_launch(dict(kid), MONDAY.isoformat()) is None,
                  "no bus line when school is out")


SCENARIOS = [
    scenario_unconfigured_is_plain_weekdays,
    scenario_year_bounds_mark_summer_out,
    scenario_no_school_calendar_events,
    scenario_custom_keywords,
    scenario_fetch_failure_fails_open,
    scenario_auto_year_bounds_from_markers,
    scenario_open_ended_year_and_manual_override,
    scenario_bus_launch_honors_the_gate,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
