"""Tests for services/ics_sync.py (intake arc phase 1).

Covers ICS parsing (single, recurring, all-day; key scheme; fingerprints) and
the sync diff (create/patch/delete, past-event protection, retry-on-failure).
No network, no real Google Calendar, never touches data/.

Run from chauffeur/:  python tests/test_ics_sync.py
"""
import atexit
import datetime
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_ics_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ics_sync, storage  # noqa: E402

PASS = 0
FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def _utc(dt):
    return dt.astimezone(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


NOW = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)


def build_ics(events, name="Fall Soccer"):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//EN",
             f"X-WR-CALNAME:{name}"]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev['uid']}")
        if ev.get('all_day'):
            lines.append(f"DTSTART;VALUE=DATE:{ev['start'].strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{ev['end'].strftime('%Y%m%d')}")
        else:
            lines.append(f"DTSTART:{_utc(ev['start'])}")
            lines.append(f"DTEND:{_utc(ev['end'])}")
        if ev.get('rrule'):
            lines.append(f"RRULE:{ev['rrule']}")
        lines.append(f"SUMMARY:{ev['summary']}")
        if ev.get('location'):
            lines.append(f"LOCATION:{ev['location']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode('utf-8')


class FakeGcal:
    def __init__(self):
        self.inserted = []      # (cal_id, body)
        self.patched = []       # (cal_id, gid, body)
        self.removed = []       # (cal_id, gid)
        self.fail_remove = False
        self._next = 0

    def insert_event(self, cal_id, body):
        self._next += 1
        gid = f"g{self._next}"
        self.inserted.append((cal_id, gid, body))
        return gid

    def patch_event(self, cal_id, gid, body):
        self.patched.append((cal_id, gid, body))
        return True

    def remove_event(self, cal_id, gid):
        if self.fail_remove:
            return False
        self.removed.append((cal_id, gid))
        return True


def test_parse():
    print("parse_ics ...")
    single = {'uid': 'single-1', 'start': NOW + datetime.timedelta(days=7),
              'end': NOW + datetime.timedelta(days=7, hours=1),
              'summary': 'Practice', 'location': 'Field 4'}
    rec = {'uid': 'rec-1', 'start': NOW + datetime.timedelta(days=8),
           'end': NOW + datetime.timedelta(days=8, hours=1),
           'summary': 'Game', 'rrule': 'FREQ=WEEKLY;COUNT=3'}
    allday = {'uid': 'allday-1', 'all_day': True,
              'start': (NOW + datetime.timedelta(days=20)).date(),
              'end': (NOW + datetime.timedelta(days=21)).date(),
              'summary': 'No School'}
    parsed = ics_sync.parse_ics(build_ics([single, rec, allday]))

    check(parsed['name'] == 'Fall Soccer', f"feed name: {parsed['name']}")
    items = parsed['items']
    check(len(items) == 5, f"expected 5 occurrences (1+3+1), got {len(items)}")
    check('single-1' in items, "single event keyed by bare uid")
    rec_keys = [k for k in items if k.startswith('rec-1::')]
    check(len(rec_keys) == 3, f"recurring occurrences keyed uid::start, got {rec_keys}")
    check('allday-1' in items, "all-day event keyed by bare uid")
    check(items['allday-1']['all_day'] is True, "all-day flag set")
    check(len(items['allday-1']['start']) == 10, "all-day start is a bare date")
    check(items['single-1']['location'] == 'Field 4', "location parsed")
    fps = {it['fingerprint'] for it in items.values()}
    check(len(fps) == 5, "fingerprints are distinct")


def test_sync_lifecycle():
    print("sync_feed lifecycle ...")
    fake = FakeGcal()
    real_gcal, real_fetch = ics_sync.gcal, ics_sync.fetch_ics
    ics_sync.gcal = fake

    fut = {'uid': 'fut-1', 'start': NOW + datetime.timedelta(days=7),
           'end': NOW + datetime.timedelta(days=7, hours=1), 'summary': 'Practice'}
    gone = {'uid': 'gone-1', 'start': NOW + datetime.timedelta(days=10),
            'end': NOW + datetime.timedelta(days=10, hours=1), 'summary': 'Game'}
    past = {'uid': 'past-1', 'start': NOW - datetime.timedelta(days=1),
            'end': NOW - datetime.timedelta(hours=23), 'summary': 'Old Practice'}

    try:
        feed_id = storage.add_ics_feed({'url': 'https://x/test.ics', 'name': 'T',
                                        'calendar_id': 'kid@cal'})

        # -- first sync: all three created
        ics_sync.fetch_ics = lambda url: build_ics([fut, gone, past])
        res = ics_sync.sync_feed(storage.get_ics_feed(feed_id))
        check(res['added'] == 3 and res['error'] is None, f"first sync creates 3: {res}")
        feed = storage.get_ics_feed(feed_id)
        check(feed['event_count'] == 3, "event_count persisted")
        check(len(feed['event_map']) == 3, "event_map has 3 entries")
        check(feed['last_status'].startswith('ok: 3 events'), f"status: {feed['last_status']}")
        body = fake.inserted[0][2]
        priv = body['extendedProperties']['private']
        check(priv['ics_feed_id'] == feed_id, "events tagged with feed id")

        # -- second sync: fut-1 shifted (patch), gone-1 dropped (delete), past-1 dropped (kept)
        fut2 = dict(fut, start=fut['start'] + datetime.timedelta(hours=1),
                    end=fut['end'] + datetime.timedelta(hours=1))
        ics_sync.fetch_ics = lambda url: build_ics([fut2])
        res = ics_sync.sync_feed(storage.get_ics_feed(feed_id))
        check(res['added'] == 0 and res['updated'] == 1 and res['removed'] == 1,
              f"second sync patches 1, removes 1: {res}")
        feed = storage.get_ics_feed(feed_id)
        check('past-1' in feed['event_map'], "past event kept as history, not deleted")
        check(len(fake.removed) == 1, "only the future vanished event was deleted from GCal")
        check(len(fake.patched) == 1, "time change patched in place")

        # -- unchanged sync: no ops
        res = ics_sync.sync_feed(storage.get_ics_feed(feed_id))
        check(res['added'] == 0 and res['updated'] == 0 and res['removed'] == 0,
              f"idempotent re-sync: {res}")

        # -- delete failure: entry retained for retry
        gone2 = {'uid': 'gone-2', 'start': NOW + datetime.timedelta(days=12),
                 'end': NOW + datetime.timedelta(days=12, hours=1), 'summary': 'Scrimmage'}
        ics_sync.fetch_ics = lambda url: build_ics([fut2, gone2])
        ics_sync.sync_feed(storage.get_ics_feed(feed_id))
        fake.fail_remove = True
        ics_sync.fetch_ics = lambda url: build_ics([fut2])
        res = ics_sync.sync_feed(storage.get_ics_feed(feed_id))
        check(res['removed'] == 0, "failed delete not counted")
        feed = storage.get_ics_feed(feed_id)
        check('gone-2' in feed['event_map'], "failed delete retained for retry")
        fake.fail_remove = False
        res = ics_sync.sync_feed(storage.get_ics_feed(feed_id))
        check(res['removed'] == 1, "retried delete succeeds next sync")

        # -- feed fetch error: recorded, map untouched
        def boom(url):
            raise ValueError("500 from server")
        ics_sync.fetch_ics = boom
        before = storage.get_ics_feed(feed_id)['event_map']
        res = ics_sync.sync_feed(storage.get_ics_feed(feed_id))
        check(res['error'] is not None, "fetch error surfaces in summary")
        feed = storage.get_ics_feed(feed_id)
        check(feed['last_status'].startswith('error:'), "error recorded in status")
        check(feed['event_map'] == before, "event_map untouched on fetch error")

        # -- remove_feed_events: only future events deleted
        fake.removed = []
        removed = ics_sync.remove_feed_events(storage.get_ics_feed(feed_id))
        feed = storage.get_ics_feed(feed_id)
        future_entries = [k for k in feed['event_map'] if k != 'past-1']
        check(removed == len(future_entries), f"removed {removed} future events (expected {len(future_entries)})")
        check(('kid@cal', feed['event_map']['past-1']['gid']) not in fake.removed,
              "past event survives feed deletion cleanup")
    finally:
        ics_sync.gcal = real_gcal
        ics_sync.fetch_ics = real_fetch


if __name__ == '__main__':
    test_parse()
    test_sync_lifecycle()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
