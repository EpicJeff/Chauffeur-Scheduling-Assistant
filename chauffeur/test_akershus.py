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

from services.trip_planner import schedule_poi, _find_slots
import services.trip_planner

original_find_slots = services.trip_planner._find_slots

def debug_find_slots(trip, duration_mins, is_food, location, bounds=None, avoid_overlap=True, valid_days=None, force_date=None, target_start=None, target_end=None, is_nightlife=False, is_dessert=False):
    print(f"_find_slots called bounds={bounds}")
    slots = original_find_slots(trip, duration_mins, is_food, location, bounds, avoid_overlap, valid_days, force_date, target_start, target_end, is_nightlife, is_dessert)
    print(f"_find_slots returned {len(slots)} slots")
    for s, score in slots:
        print(f"Slot: {s.astimezone(zoneinfo.ZoneInfo('America/New_York'))}, Score: {score}")
    return slots

services.trip_planner._find_slots = debug_find_slots

tz = zoneinfo.ZoneInfo("America/New_York")

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None

for p in trip.pois:
    if "Akershus" in p.name:
        schedule_poi(trip, p)
