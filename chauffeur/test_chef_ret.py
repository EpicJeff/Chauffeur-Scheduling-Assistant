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
    if p.is_background and "Day 3" in p.name:
        p.is_scheduled = True
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None

import services.trip_planner
original_find_slots = services.trip_planner._find_slots

def debug_find_slots(trip, duration_mins, is_food, location, bounds=None, avoid_overlap=True, valid_days=None, force_date=None, target_start=None, target_end=None, is_nightlife=False, is_dessert=False):
    slots = original_find_slots(trip, duration_mins, is_food, location, bounds, avoid_overlap, valid_days, force_date, target_start, target_end, is_nightlife, is_dessert)
    print(f"_find_slots RETURNED: {len(slots)} slots")
    for s, t in slots:
        print(f"  Score: {s}, Time: {t.astimezone(zoneinfo.ZoneInfo('America/New_York'))}")
    return slots

services.trip_planner._find_slots = debug_find_slots
services.trip_planner.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Chef Mickey" in p.name:
        print("Testing Chef Mickey WITH BOUNDS...")
        res = services.trip_planner.schedule_poi(trip, p, bounds=(a_start, a_end))
        print("RESULT:", res)
