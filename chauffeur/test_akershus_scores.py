import json
from models.schemas import TripMetadata
import datetime
import zoneinfo
import sys
import unittest.mock as mock

db = json.load(open("data/db.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
trip.is_draft = True
trip.mock_start_date = int(datetime.datetime.now().timestamp())
trip.mock_end_date = trip.mock_start_date + (7 * 86400)

class MockEvent:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.id = "trip123"
        self.calendar_ids = ["dummy"]
trip.event_id = "trip123"

mock_storage = mock.MagicMock()
mock_storage.get_settings.return_value = {"calendar_ids": ["dummy"]}
sys.modules['services.storage'] = mock_storage
sys.modules['services.calendar'] = mock.MagicMock()
sys.modules['services.calendar'].get_events.return_value = [
    MockEvent(
        datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(trip.mock_end_date, tz=datetime.timezone.utc)
    )
]

a_start = None
a_end = None
for p in trip.pois:
    if p.is_background and "Day 6" in p.name:
        p.is_scheduled = True
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None

for p in trip.pois:
    if "Woody's" in p.name:
        p.is_scheduled = True
        dt = datetime.datetime.fromisoformat("2026-08-16T10:30:00-04:00")
        p.scheduled_start = int(dt.timestamp())
        p.scheduled_end = p.scheduled_start + 60*60

import services.trip_planner

with open("services/trip_planner.py", "r") as f:
    original_code = f.read()

hack_code = original_code.replace(
    "valid_slots.sort(key=lambda x: (-x[0], x[1]))",
    "valid_slots.sort(key=lambda x: (-x[0], x[1]))\n    for s, sc in valid_slots:\n        print(sc.astimezone(local_tz), s)"
)

with open("services/trip_planner_hacked.py", "w") as f:
    f.write(hack_code)

import importlib
sys.path.insert(0, ".")
import services.trip_planner_hacked
services.trip_planner_hacked.maps = services.trip_planner.maps
services.trip_planner_hacked.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Akershus" in p.name:
        print("Testing Akershus WITH BOUNDS...")
        services.trip_planner_hacked.schedule_poi(trip, p, bounds=(a_start, a_end))
