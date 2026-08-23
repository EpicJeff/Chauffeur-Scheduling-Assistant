"""The dual-income safety net (load arc A5).

Load-bearing properties:

  1. **School days get kinds.** The boolean was blind to the half day —
     nobody has PTO booked for a half day — and to late starts. Timed events
     still never shorten a day; kinds fail toward 'full' exactly as the
     boolean fails open.
  2. **Aftercare is a care window.** On an aftercare day the pickup deadline
     is the aftercare end, not the bell, the dismissal push says so, and a
     half day covered by aftercare is NOT a gap.
  3. **Gaps are said weeks ahead, as decisions with named options** — the
     3-day watcher window is far too late to book a day off.
  4. **The status→solver injection runs the full build horizon** — a cover
     day 20 days out was announced to everyone while the solver kept
     scheduling that parent.

Run from chauffeur/:  python tests/test_care_gaps.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import school, storage

TODAY = datetime.date.today()


def _weekday_ahead(days_min=2):
    """The first weekday at least `days_min` days out — the gap horizon skips
    weekends, and so must the fixtures."""
    d = TODAY + datetime.timedelta(days=days_min)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d


def _prime_school_cache(dates=None, kinds=None):
    with school._lock:
        school._cache.update({
            'ts': 9e12, 'fail_ts': 0.0, 'cal_id': 'school@cal',
            'start': TODAY - datetime.timedelta(days=30),
            'end': TODAY + datetime.timedelta(days=60),
            'dates': dates or set(), 'intervals': [], 'kinds': kinds or {}})


def _reset(settings=None):
    storage.members_table.truncate()
    base = {'school_calendar_id': 'school@cal'}
    base.update(settings or {})
    storage.get_settings = lambda: base
    school._reset_cache()


def _kid(name, **kw):
    from models.schemas import FamilyMember
    m = FamilyMember(name=name, role='child', **kw).model_dump()
    storage.add_member(m)
    return m


def scenario_a_school_day_has_a_kind():
    _reset()
    half = _weekday_ahead(2)
    closed = _weekday_ahead(4) if _weekday_ahead(4) != half else _weekday_ahead(5)
    delayed = _weekday_ahead(7)
    _prime_school_cache(dates={closed.isoformat()},
                        kinds={half.isoformat(): 'half',
                               delayed.isoformat(): 'delayed'})
    check(school.school_day_kind(half) == 'half', "the half day is seen")
    check(school.school_day_kind(closed) == 'closed', "closure comes through the boolean")
    check(school.school_day_kind(delayed) == 'delayed', "and the late start is its own kind")
    ordinary = _weekday_ahead(9)
    if ordinary in (half, closed, delayed):
        ordinary = _weekday_ahead(10)
    check(school.school_day_kind(ordinary) == 'full', "an ordinary weekday is full")
    saturday = TODAY + datetime.timedelta(days=(5 - TODAY.weekday()) % 7 or 7)
    check(school.school_day_kind(saturday) == 'weekend',
          "weekends are their own shape, never a gap")


def scenario_kinds_fail_toward_full_like_the_boolean_fails_open():
    _reset(settings={'school_calendar_id': ''})
    check(school.school_day_kind(_weekday_ahead(3)) == 'full',
          "no calendar: never invent closures")
    check(school.school_day_kind('not-a-date') == 'full',
          "garbage in, full out — a broken caller must not conjure a gap")


def scenario_the_half_day_keywords_parse_from_the_calendar():
    """The sneaky day arrives as an all-day 'Early Release' event. A TIMED
    early-release event still does nothing, same as closure detection."""
    d = _weekday_ahead(3)
    events = [
        {'summary': 'Early Release Day',
         'start': {'date': d.isoformat()},
         'end': {'date': (d + datetime.timedelta(days=1)).isoformat()}},
        {'summary': 'Two Hour Delay',
         'start': {'date': (d + datetime.timedelta(days=1)).isoformat()},
         'end': {'date': (d + datetime.timedelta(days=2)).isoformat()}},
        {'summary': 'early dismissal assembly',        # timed: inert
         'start': {'dateTime': f"{d.isoformat()}T10:00:00"},
         'end': {'dateTime': f"{d.isoformat()}T11:00:00"}},
    ]
    from unittest import mock
    with mock.patch('services.calendar._fetch_single_calendar',
                    return_value=('school@cal', events)):
        data = school._fetch_school_data('school@cal', TODAY,
                                         TODAY + datetime.timedelta(days=30),
                                         school._keywords({}))
    dates, _intervals, kinds = data
    check(kinds.get(d.isoformat()) == 'half', f"all-day early release parses: {kinds}")
    check(kinds.get((d + datetime.timedelta(days=1)).isoformat()) == 'delayed',
          "and the two-hour delay")
    check(not dates, "neither closed the school outright")


def scenario_gaps_are_found_weeks_ahead():
    _reset()
    _kid("Lily")
    far = _weekday_ahead(15)     # far outside the 3-day watcher window
    _prime_school_cache(dates={far.isoformat()})
    gaps = school.care_gap_days(21)
    check(any(g['date'] == far.isoformat() and g['kind'] == 'closed' for g in gaps),
          f"a closure 15 days out is a gap TODAY — PTO needs lead time: {gaps}")

    _reset()   # no kids
    _prime_school_cache(dates={far.isoformat()})
    check(school.care_gap_days(21) == [],
          "a house with no children has no childcare gaps")


def scenario_aftercare_softens_a_half_day_but_not_a_closure():
    """Aftercare is what a half day is FOR. A closure closes aftercare with
    the school, so nothing softens it."""
    from services import watchers
    _reset()
    half = _weekday_ahead(6)
    closed = _weekday_ahead(10)
    if closed == half:
        closed = _weekday_ahead(11)
    _kid("Lily", aftercare_days=[half.weekday()], aftercare_until='17:30',
         aftercare_place='Extended Day')
    _prime_school_cache(dates={closed.isoformat()},
                        kinds={half.isoformat(): 'half'})

    msgs = [f.line for f in watchers._care_gap_findings(datetime.datetime.now())]
    check(not any('half day' in m for m in msgs),
          f"her aftercare has the half-day afternoon — not a gap: {msgs}")
    check(any('no school' in m for m in msgs),
          f"the closure still is one: {msgs}")

    # A second kid without aftercare re-opens the half day, and is NAMED.
    _kid("James")
    msgs = [f.line for f in watchers._care_gap_findings(datetime.datetime.now())]
    half_msgs = [m for m in msgs if 'half day' in m]
    check(half_msgs and 'James' in half_msgs[0] and 'Lily' not in half_msgs[0],
          f"the finding names who needs covering, not who is fine: {half_msgs}")


def scenario_summer_is_a_break_not_a_wall_of_closures():
    """2026-08-10: with the school year over, every weekday in the 21-day
    horizon read as 'closed' and Argyle sent a no-school line for each one.
    A day outside the school year is a 'break' — a season the family plans
    for — and never a care gap. 'closed' is reserved for closures DURING
    the year."""
    from services import watchers
    # Manual bounds: the year ended a month ago.
    _reset(settings={'school_year_end':
                     (TODAY - datetime.timedelta(days=30)).isoformat()})
    _kid("Lily")
    _prime_school_cache()
    check(school.school_day_kind(_weekday_ahead(5)) == 'break',
          "outside the year is a break, not a closure")
    check(school.care_gap_days(21) == [],
          "summer weekdays are not care gaps")
    check(watchers._care_gap_findings(datetime.datetime.now()) == [],
          "and Argyle says nothing about them")

    # Auto-detected intervals say the same thing without manual bounds.
    _reset()
    _kid("Lily")
    _prime_school_cache()
    with school._lock:
        school._cache['intervals'] = [(TODAY - datetime.timedelta(days=330),
                                       TODAY - datetime.timedelta(days=30), False)]
    check(school.school_day_kind(_weekday_ahead(5)) == 'break',
          "detected intervals gate the pings the same way")
    check(school.care_gap_days(21) == [],
          "no gaps between detected school years either")


def scenario_the_finding_is_a_decision_not_an_alarm():
    from services import watchers
    _reset()
    _kid("Lily")
    closed = _weekday_ahead(8)
    _prime_school_cache(dates={closed.isoformat()})
    found = watchers._care_gap_findings(datetime.datetime.now())
    check(found, "the gap is found")
    key, msg = found[0].key, found[0].line
    check('carpool family' in msg and 'grandparent' in msg,
          f"named options, the occasions-decisions voice: {msg}")
    check('🚨' not in msg, "and it is not dressed as an emergency")
    check(key == f"caregap:{closed.isoformat()}:closed",
          f"keyed per (day, kind) so it is said once: {key}")


def scenario_the_dismissal_push_tells_the_aftercare_truth():
    """On an aftercare day the push leads with the real shape of the
    afternoon — 'Extended Day until 5:30, Mom gets you' — instead of a ride
    at the bell that is not coming."""
    import main
    _reset()
    kid = _kid("Lily", school_hours_end='15:00',
               aftercare_days=[TODAY.weekday()], aftercare_until='17:30',
               aftercare_place='Extended Day')
    sent = []
    orig_notify, orig_day = main._notify_member_lanes, main.member_day
    try:
        main._notify_member_lanes = lambda m, title, body, path: sent.append((title, body))
        main.member_day = lambda mid, date=None: {'rides': [
            {'start': f"{TODAY.isoformat()}T17:30:00",
             'title': 'Pickup', 'driver': {'name': 'Mom'}, 'legs': []}]}
        now = datetime.datetime.combine(TODAY, datetime.time(15, 0))
        ok = main._send_school_end_push(kid, now=now)
        check(ok and sent, "the push goes out")
        title, body = sent[0]
        check('Extended Day' in title, f"named what the kid calls it: {title}")
        check('5:30' in body and 'Mom' in body,
              f"the real deadline and the real driver: {body}")
    finally:
        main._notify_member_lanes, main.member_day = orig_notify, orig_day


def scenario_the_status_injection_covers_the_build_horizon():
    """A cover day 20 days out was announced to the whole family while the
    solver went right on scheduling that parent for it."""
    import re
    src = open('main.py', encoding='utf-8').read()
    src_flat = re.sub(r'\s+', ' ', src)
    check("timedelta(days=14)" not in src_flat.split('unavailable_driver_dates')[0][-600:],
          "the hardcoded 14-day window is gone")
    check("settings.get('days_to_build'" in src,
          "the injection reads the same horizon the solver builds")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} care-gap scenarios passed")
