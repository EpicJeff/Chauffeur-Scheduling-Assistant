"""One bad calendar id must not take the whole household's schedule down.

Regression cover for v2.273.6: an ICS feed URL pasted into Config -> Calendar
IDs became a permanent Google 404. fetch_upcoming_events raised on it, the
refresh returned {"error": ...} instead of a schedule, and every event lost
its passenger attribution. The rule now:

  - PERMANENT failure (400/401/403/404/410): skip that calendar, remember it,
    keep serving the rest of the family.
  - TRANSIENT failure (500, timeout, ...): still abort, because a half-fetched
    day is indistinguishable from "everything was cancelled" and gets cached.

Also covers the geocoder guard: a LOCATION that is only a link is not a place.

Run from chauffeur/:  python tests/test_calendar_resilience.py
"""
import atexit
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_calres_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock  # noqa: E402

from services import calendar as gcal  # noqa: E402
from services import maps  # noqa: E402

PASS = 0
FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


class FakeResp:
    def __init__(self, status):
        self.status = status


class FakeHttpError(Exception):
    """Shaped like googleapiclient.errors.HttpError (it carries .resp.status)."""

    def __init__(self, status):
        super().__init__(f"HttpError {status}")
        self.resp = FakeResp(status)


ICS_URL = "https://calendar.playmetrics.com/calendars/c1/t558748/p0/t33250F99/f/calendar.ics"

GOOD_EVENT = {
    'id': 'evt1',
    'summary': 'Soccer practice',
    'start': {'dateTime': '2026-08-18T17:00:00-04:00'},
    'end': {'dateTime': '2026-08-18T18:00:00-04:00'},
    'location': '1200 High House Rd, Cary, NC 27513, USA',
}


def _fake_fetch(good_ids, failures):
    """failures: {cal_id: exception to raise}."""
    def _inner(cal_id, time_min, time_max):
        if cal_id in failures:
            print(f"Error fetching from calendar {cal_id}: {failures[cal_id]}")
            if gcal._is_unreadable(failures[cal_id]):
                gcal._note_unreadable_calendar(cal_id)
            return cal_id, None
        gcal._clear_unreadable_calendar(cal_id)
        return cal_id, ([GOOD_EVENT] if cal_id in good_ids else [])
    return _inner


def _reset():
    for cid in list(gcal.get_unreadable_calendars()):
        gcal._clear_unreadable_calendar(cid)


def test_unreadable_is_skipped():
    print("test_unreadable_is_skipped")
    _reset()
    cals = ['kid@group.calendar.google.com', ICS_URL]
    fake = _fake_fetch({'kid@group.calendar.google.com'}, {ICS_URL: FakeHttpError(404)})

    with mock.patch.object(gcal, '_fetch_single_calendar', side_effect=fake):
        events = gcal.fetch_upcoming_events(cals, start_date_str='2026-08-18',
                                            end_date_str='2026-08-18')

    check(len(events) == 1, f"the good calendar still yields its event (got {len(events)})")
    check(events and events[0].title == 'Soccer practice', "event survived intact")
    check(ICS_URL in gcal.get_unreadable_calendars(), "bad id recorded as unreadable")


def test_every_permanent_status_is_skipped():
    print("test_every_permanent_status_is_skipped")
    for status in gcal.UNREADABLE_STATUSES:
        _reset()
        cals = ['kid@cal', 'bad@cal']
        fake = _fake_fetch({'kid@cal'}, {'bad@cal': FakeHttpError(status)})
        with mock.patch.object(gcal, '_fetch_single_calendar', side_effect=fake):
            try:
                events = gcal.fetch_upcoming_events(cals, start_date_str='2026-08-18',
                                                    end_date_str='2026-08-18')
                ok = len(events) == 1
            except Exception:
                ok = False
        check(ok, f"HTTP {status} is skipped, not fatal")


def test_transient_still_aborts():
    print("test_transient_still_aborts")
    _reset()
    cals = ['kid@cal', 'flaky@cal']
    fake = _fake_fetch({'kid@cal'}, {'flaky@cal': FakeHttpError(500)})

    raised = False
    with mock.patch.object(gcal, '_fetch_single_calendar', side_effect=fake):
        try:
            gcal.fetch_upcoming_events(cals, start_date_str='2026-08-18',
                                       end_date_str='2026-08-18')
        except Exception as ex:
            raised = 'Aborting to prevent cache poisoning' in str(ex)
    check(raised, "a transient 500 still aborts (cache-poisoning guard intact)")
    check('flaky@cal' not in gcal.get_unreadable_calendars(),
          "a transient failure is NOT quarantined")


def test_recovery_clears_quarantine():
    print("test_recovery_clears_quarantine")
    _reset()
    gcal._note_unreadable_calendar('kid@cal')
    fake = _fake_fetch({'kid@cal'}, {})
    with mock.patch.object(gcal, '_fetch_single_calendar', side_effect=fake):
        gcal.fetch_upcoming_events(['kid@cal'], start_date_str='2026-08-18',
                                   end_date_str='2026-08-18')
    check('kid@cal' not in gcal.get_unreadable_calendars(),
          "a calendar that reads again clears itself")


def test_looks_like_feed_url():
    print("test_looks_like_feed_url")
    check(gcal.looks_like_feed_url(ICS_URL), "the PlayMetrics URL is caught")
    check(gcal.looks_like_feed_url('webcal://team.com/x'), "webcal:// is caught")
    check(gcal.looks_like_feed_url('http://a.com/b.ics'), "http .ics is caught")
    check(gcal.looks_like_feed_url('  HTTPS://A.COM/x  '), "case/space tolerant")
    check(not gcal.looks_like_feed_url('family@group.calendar.google.com'),
          "a real calendar id is allowed")
    check(not gcal.looks_like_feed_url('primary'), "'primary' is allowed")
    check(not gcal.looks_like_feed_url(''), "empty is not a feed url")


def test_link_only_location_is_not_a_place():
    print("test_link_only_location_is_not_a_place")
    # The exact string that geocoded to Paces, Virginia -- 130 miles away.
    check(maps.strip_url_noise('https://tickets.nccourage.com/pages/courage-ncfc-youth') == '',
          "a ticket link is not a place")
    check(maps.strip_url_noise('webcal://x.com/y') == '', "webcal link is not a place")
    check(maps.strip_url_noise('www.example.com') == '', "bare www link is not a place")

    addr = '1200 High House Rd, Cary, NC 27513, USA'
    check(maps.strip_url_noise(addr) == addr, "a real address passes through untouched")
    check(maps.strip_url_noise('Mills Park Middle School') == 'Mills Park Middle School',
          "a bare venue name still passes (agent-created events depend on it)")

    mixed = 'Prestonwood Soccer Complex, 1200 High House Rd, Cary NC https://tickets.com/x'
    out = maps.strip_url_noise(mixed)
    check('1200 High House Rd' in out and 'https' not in out,
          "a real address beside a link keeps the address, drops the link")

    # No network: the guard must settle before any API call is considered.
    with mock.patch.object(maps, '_geocode_address_api_lookup',
                           side_effect=AssertionError('geocoder must not be called')):
        check(maps.geocode_address('https://tickets.nccourage.com/pages/x') is None,
              "geocode_address returns None for a link, without calling the API")


if __name__ == '__main__':
    test_unreadable_is_skipped()
    test_every_permanent_status_is_skipped()
    test_transient_still_aborts()
    test_recovery_clears_quarantine()
    test_looks_like_feed_url()
    test_link_only_location_is_not_a_place()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
