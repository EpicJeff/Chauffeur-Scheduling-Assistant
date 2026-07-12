import json
import sys
import unittest.mock as mock
mock_storage = mock.MagicMock()
mock_storage.get_settings.return_value = {"calendar_ids": ["dummy"]}
sys.modules['services.storage'] = mock_storage

from models.schemas import TripMetadata
import datetime
import zoneinfo
db = json.load(open("data/db_copy.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
trip.is_draft = True
trip.mock_start_date = int(datetime.datetime.now().timestamp())
trip.mock_end_date = trip.mock_start_date + (7 * 86400)

mk = next((p for p in trip.pois if "Magic Kingdom Park (Day 1)" == p.name), None)
if mk and mk.scheduled_start:
    a_start = datetime.datetime.fromtimestamp(mk.scheduled_start, tz=datetime.timezone.utc)
    a_end = datetime.datetime.fromtimestamp(mk.scheduled_end, tz=datetime.timezone.utc)
    print(f"MK1 bounds: {a_start} to {a_end}")

from services.trip_planner import schedule_poi
for p in trip.pois:
    if "Be Our Guest" in p.name:
        print(f"Testing schedule_poi for {p.name}")
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None
        event_id, reason, meta = schedule_poi(trip, p, bounds=(a_start, a_end))
        print(f"Result: event_id={event_id}, reason={reason}")
        if not event_id:
            print("FAILED TO SCHEDULE! Why?")
            print(f"Constraints: ideal_time_start={p.ideal_time_start}, valid_days={p.valid_days_of_week}, duration={p.duration_mins}")
