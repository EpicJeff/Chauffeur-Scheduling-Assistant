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

mk3_bounds = None
for p in trip.pois:
    if p.is_background and "Magic Kingdom Park (Day 3)" in p.name:
        mk3_bounds = (
            datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc),
            datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)
        )
trip.mock_start_date = mk3_bounds[0].timestamp()
trip.mock_end_date = mk3_bounds[1].timestamp()

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
    MockEvent(mk3_bounds[0], mk3_bounds[1])
]
trip.event_id = "trip123"

# Hack trip_planner to force enforce_ideal_times=True to fail
with open("services/trip_planner.py", "r") as f:
    code = f.read()
code = code.replace(
    "valid_slots = find_slots(enforce_ideal_times=True)",
    "valid_slots = []"
)
with open("services/trip_planner_hacked10.py", "w") as f:
    f.write(code)

sys.path.insert(0, ".")
import services.trip_planner_hacked10
services.trip_planner_hacked10.maps = services.trip_planner.maps
services.trip_planner_hacked10.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Chef Mickey" in p.name:
        print("Testing Chef Mickey forced failure...")
        # Note: Chef Mickey has valid_days_of_week = [3] (Thursday) in db.json!
        # But MK3 is Tuesday (day 1)!
        res = services.trip_planner_hacked10.schedule_poi(trip, p, bounds=mk3_bounds)
        print("RESULT:", res)
