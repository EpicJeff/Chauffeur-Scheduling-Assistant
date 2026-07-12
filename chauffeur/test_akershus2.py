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

mock_storage = mock.MagicMock()
mock_storage.get_settings.return_value = {"calendar_ids": ["dummy"]}
sys.modules['services.storage'] = mock_storage

from services.trip_planner import schedule_poi

for p in trip.pois:
    if p.is_background and "Day 6" in p.name:
        p.is_scheduled = True

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None

# Woody's Lunch Box is scheduled at 10:30 on Day 6
for p in trip.pois:
    if "Woody's" in p.name:
        p.is_scheduled = True
        dt = datetime.datetime.fromisoformat("2026-08-21T10:30:00-04:00")
        p.scheduled_start = int(dt.timestamp())
        p.scheduled_end = p.scheduled_start + 60*60

# We need to hack find_slots to print the scores
import services.trip_planner

with open("services/trip_planner.py", "r") as f:
    original_code = f.read()

hack_code = original_code.replace("return slots[0][0]", "for s, sc in slots: print(s.astimezone(local_tz), sc)\n        return slots[0][0]")

with open("services/trip_planner_hacked.py", "w") as f:
    f.write(hack_code)

import importlib
sys.path.insert(0, ".")
import services.trip_planner_hacked
services.trip_planner_hacked.maps = services.trip_planner.maps
services.trip_planner_hacked.calendar = services.trip_planner.calendar

for p in trip.pois:
    if "Akershus" in p.name:
        services.trip_planner_hacked.schedule_poi(trip, p)
