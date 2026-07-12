import json
from models.schemas import TripMetadata
import datetime
import zoneinfo
import services.storage as storage

db = json.load(open("data/db.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
trip.is_draft = True
trip.mock_start_date = int(datetime.datetime.now().timestamp())
trip.mock_end_date = trip.mock_start_date + (7 * 86400)

import sys
import unittest.mock as mock
mock_storage = mock.MagicMock()
mock_storage.get_settings.return_value = {"calendar_ids": ["dummy"]}
sys.modules['services.storage'] = mock_storage

from services.trip_planner import schedule_poi

tz = zoneinfo.ZoneInfo("America/New_York")

a_start = None
a_end = None
for p in trip.pois:
    if p.is_background and "Day 3" in p.name:
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)
        print(f"ANCHOR: {p.name} bounds: {a_start.astimezone(tz)} to {a_end.astimezone(tz)}")

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None

for p in trip.pois:
    if "Chef Mickey" in p.name:
        print(f"Testing schedule_poi WITH BOUNDS for {p.name}")
        event_id, reason, meta = schedule_poi(trip, p, bounds=(a_start, a_end))
        print(f"Result: event_id={event_id}, reason={reason}")
        if not event_id:
            print("FAILED TO SCHEDULE WITH BOUNDS! Why?")
            print(f"Constraints: ideal_time_start={p.ideal_time_start}, valid_days={p.valid_days_of_week}, duration={p.duration_mins}")
            if meta:
                print(meta)
