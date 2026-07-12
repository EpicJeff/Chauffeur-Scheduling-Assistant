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
        print("ANCHOR BOUNDS:", a_start, a_end)

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None

import services.trip_planner

with open("services/trip_planner.py", "r") as f:
    original_code = f.read()

# I will hack the find_slots to print ALL reasons why slots are skipped!
import re

hack_code = re.sub(
    r"(\s+if slot_time < earliest_time:\n\s+)continue",
    r'\1print("Failed: earliest_time")\n\g<1>continue',
    original_code
)
hack_code = re.sub(
    r'(\s+if slot_time > hard_cap_start and not \(poi.ideal_time_end and "23" in poi.ideal_time_end\):\n\s+)continue',
    r'\1print("Failed: hard_cap")\n\g<1>continue',
    hack_code
)
hack_code = re.sub(
    r'(\s+if getattr\(poi, \'valid_days_of_week\', None\):\n\s+if slot_local.weekday\(\) not in poi.valid_days_of_week:\n\s+)continue',
    r'\1print("Failed: valid_days")\n\g<1>continue',
    hack_code
)
hack_code = re.sub(
    r'(\s+# Add a 15-minute grace period to the ideal window\n\s+if s_slot < \(s_mins - 15\) or s_slot > \(e_mins \+ 15\):\n\s+)continue',
    r'\1print("Failed: ideal_times start (s_slot=", s_slot, " s_mins=", s_mins, " e_mins=", e_mins, " slot_time=", slot_time, ")")\n\g<1>continue',
    hack_code
)
hack_code = re.sub(
    r'(\s+# The end shouldn\'t be more than 2 hours past the ideal end time\n\s+if e_slot > \(e_mins \+ 120\):\n\s+)continue',
    r'\1print("Failed: ideal_times end")\n\g<1>continue',
    hack_code
)
hack_code = re.sub(
    r'(\s+if overlaps:\n\s+)continue',
    r'\1print("Failed: overlaps")\n\g<1>continue',
    hack_code
)
hack_code = re.sub(
    r'(\s+if conflict:\n\s+)continue',
    r'\1print("Failed: meal conflict")\n\g<1>continue',
    hack_code
)

with open("services/trip_planner_hacked2.py", "w") as f:
    f.write(hack_code)

import importlib
sys.path.insert(0, ".")
import services.trip_planner_hacked2
services.trip_planner_hacked2.maps = services.trip_planner.maps
services.trip_planner_hacked2.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Chef Mickey" in p.name:
        print("Testing Chef Mickey WITH BOUNDS...")
        res = services.trip_planner_hacked2.schedule_poi(trip, p, bounds=(a_start, a_end))
        print("RESULT:", res)
