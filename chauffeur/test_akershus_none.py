import json
import datetime
import zoneinfo
import sys
import unittest.mock as mock
import re

from models.schemas import TripMetadata

sys.modules['services.storage'] = mock.MagicMock()
import services.trip_planner

db = json.load(open("data/db.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))

a_start = None
a_end = None
for p in trip.pois:
    if p.is_background and "Epcot" in p.name:
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)

trip.is_draft = True
trip.mock_start_date = trip.mock_start_date or a_start.timestamp()
trip.mock_end_date = trip.mock_end_date or a_end.timestamp()

class MockEvent:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.id = "trip123"
        self.calendar_ids = ["dummy"]
        self.source_event_ids = []

sys.modules['services.calendar'] = mock.MagicMock()
services.trip_planner.calendar = sys.modules['services.calendar']
sys.modules['services.calendar'].get_events.return_value = [
    MockEvent(
        datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(trip.mock_end_date, tz=datetime.timezone.utc)
    )
]
trip.event_id = "trip123"

# Don't reset scheduled state - use db.json exactly as is

with open("services/trip_planner.py", "r") as f:
    code = f.read()
code = code.replace(
    "return slots\n        \n    valid_slots = find_slots",
    "print('RETURNED SLOTS:', slots)\n        return slots\n        \n    valid_slots = find_slots"
)
with open("services/trip_planner_hacked7.py", "w") as f:
    f.write(code)

sys.path.insert(0, ".")
import services.trip_planner_hacked7
services.trip_planner_hacked7.maps = services.trip_planner.maps
services.trip_planner_hacked7.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Akershus" in p.name:
        print("Testing Akershus with bounds=None...")
        p.valid_days_of_week = [0] # Set valid day to Monday
        res = services.trip_planner_hacked7.schedule_poi(trip, p, bounds=None)
        print("RESULT:", res)
