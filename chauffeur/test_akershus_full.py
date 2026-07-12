import json
import datetime
import zoneinfo
import sys
import unittest.mock as mock

from models.schemas import TripMetadata

sys.modules['services.storage'] = mock.MagicMock()
import services.trip_planner

db = json.load(open("data/db.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
trip.is_draft = True
trip.mock_start_date = 1786622400.0
trip.mock_end_date = 1787140800.0

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

# Hack trip_planner to print slots returned by enforce_ideal_times=False
with open("services/trip_planner.py", "r") as f:
    code = f.read()
code = code.replace(
    "valid_slots = find_slots(enforce_ideal_times=True)",
    "valid_slots = []"
)
code = code.replace(
    "alt_slots = find_slots(enforce_ideal_times=False)",
    "alt_slots = find_slots(enforce_ideal_times=False)\n            print('ALT SLOTS:', alt_slots)"
)
with open("services/trip_planner_hacked12.py", "w") as f:
    f.write(code)

sys.path.insert(0, ".")
import services.trip_planner_hacked12
services.trip_planner_hacked12.maps = services.trip_planner.maps
services.trip_planner_hacked12.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Akershus" in p.name:
        print("Testing Akershus forced failure with EXACT mock_start_date and bounds=None...")
        p.valid_days_of_week = [0] # Monday
        res = services.trip_planner_hacked12.schedule_poi(trip, p, bounds=None)
        print("RESULT:", res)
