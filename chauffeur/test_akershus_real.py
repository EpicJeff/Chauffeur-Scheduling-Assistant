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

sys.modules['services.calendar'] = mock.MagicMock()
services.trip_planner.calendar = sys.modules['services.calendar']
sys.modules['services.calendar'].get_events.return_value = []

a_start = None
a_end = None
for p in trip.pois:
    if p.is_background and "Epcot" in p.name:
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None
        
    if "Garden Grill" in p.name:
        p.is_scheduled = True
        local_tz = zoneinfo.ZoneInfo("America/New_York")
        gg_start = a_start.astimezone(local_tz).replace(hour=12, minute=0, second=0)
        gg_end = gg_start + datetime.timedelta(minutes=p.duration_mins)
        p.scheduled_start = gg_start.timestamp()
        p.scheduled_end = gg_end.timestamp()

# Hack trip_planner to print returned slots
with open("services/trip_planner.py", "r") as f:
    code = f.read()

code = code.replace(
    "return slots",
    "print('RETURNED SLOTS:', slots)\n        return slots"
)

with open("services/trip_planner_hacked5.py", "w") as f:
    f.write(code)

import importlib
sys.path.insert(0, ".")
import services.trip_planner_hacked5
services.trip_planner_hacked5.maps = services.trip_planner.maps
services.trip_planner_hacked5.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Akershus" in p.name:
        print("Testing Akershus...")
        p.valid_days_of_week = [0] # Set valid day to Monday
        res = services.trip_planner_hacked5.schedule_poi(trip, p, bounds=(a_start, a_end))
        print("RESULT:", res)
