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

sys.path.insert(0, ".")
import services.trip_planner
services.trip_planner.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if p.is_background and "Epcot" in p.name:
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)
        epcot_bounds = (a_start, a_end)

for p in trip.pois:
    if "Akershus" in p.name:
        print("Testing Akershus with BOUNDS...")
        p.valid_days_of_week = [0] # Monday
        res = services.trip_planner.schedule_poi(trip, p, bounds=epcot_bounds)
        print("RESULT:", res)
