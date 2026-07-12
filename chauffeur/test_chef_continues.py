import json
from models.schemas import TripMetadata
import datetime
import zoneinfo
import sys
import unittest.mock as mock
import re

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
with open("services/trip_planner.py", "r") as f:
    code = f.read()

# Replace every `continue` inside find_slots with a print statement using an incrementing ID
counter = 0
def replacer(match):
    global counter
    counter += 1
    indent = match.group(1)
    return f'{indent}print("Failed continue #{counter} at", slot_time)\n{indent}continue'

code = re.sub(r'(\n\s+)continue', replacer, code)

with open("services/trip_planner_hacked4.py", "w") as f:
    f.write(code)

import importlib
sys.path.insert(0, ".")
import services.trip_planner_hacked4
services.trip_planner_hacked4.maps = services.trip_planner.maps
services.trip_planner_hacked4.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Chef Mickey" in p.name:
        print("Testing Chef Mickey WITH BOUNDS...")
        res = services.trip_planner_hacked4.schedule_poi(trip, p, bounds=(a_start, a_end))
        print("RESULT:", res)
