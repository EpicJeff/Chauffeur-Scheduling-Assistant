"""Shared harness for trip scheduler scenario tests. No network, no real DB reads."""
import datetime
import os
import sys
import tempfile
import uuid
import zoneinfo

# isolate storage before it is imported: tests must never read, write, or
# (post-SQLite-flip) migrate the real data/ directory
os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_harness_"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.schemas import TripMetadata, TripPOI, TripRule, TripAccommodation  # noqa: E402
from services import storage, maps  # noqa: E402

# --- offline mocks ----------------------------------------------------------
storage.get_settings = lambda: {"calendar_ids": ["primary"]}


def _mock_travel(a, b, *args, **kw):
    """Ten minutes between two places, nothing between a place and itself.

    Honours `return_traffic`, positionally or by keyword. The stub used to
    return a bare int whatever it was asked for, so every caller that wanted
    the traffic pair -- `matcher.get_travel_time_minutes` unpacks one -- blew
    up with "cannot unpack non-iterable int object" the moment a test reached
    real routing. A mock that does not keep the contract is a trap, not a mock.
    """
    mins = 0 if (a or "").lower() == (b or "").lower() else 10
    want_traffic = kw.get('return_traffic', args[1] if len(args) > 1 else False)
    return (mins, 0) if want_traffic else mins


maps.get_travel_time_minutes = _mock_travel
maps.get_timezone = lambda addr: "America/New_York"

ET = zoneinfo.ZoneInfo("America/New_York")
MONDAY = datetime.date(2026, 9, 7)  # a Monday


def mk_trip(days=3, start=MONDAY, location="Testville", accommodations=None, rules=None, tz="America/New_York"):
    start_dt = datetime.datetime.combine(start, datetime.time(0, 0), tzinfo=zoneinfo.ZoneInfo(tz))
    end_dt = start_dt + datetime.timedelta(days=days)
    return TripMetadata(
        id=uuid.uuid4().hex, event_id=f"draft_trip_{uuid.uuid4().hex}", is_draft=True,
        title="Test Trip", location=location, timeZone=tz,
        mock_start_date=start_dt.timestamp(), mock_end_date=end_dt.timestamp(),
        accommodations=accommodations or [], rules=rules or [],
    )


def mk_poi(name, lat=None, lng=None, **kw):
    return TripPOI(id=uuid.uuid4().hex, name=name, location=kw.pop("location", name),
                   lat=lat, lng=lng, **kw)


def mk_acc(name, lat, lng, check_in, check_out):
    return TripAccommodation(id=uuid.uuid4().hex, name=name, location=name, lat=lat, lng=lng,
                             check_in_date=check_in.strftime("%Y-%m-%d"),
                             check_out_date=check_out.strftime("%Y-%m-%d"))


def local(ts, tz=ET):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).astimezone(tz)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
