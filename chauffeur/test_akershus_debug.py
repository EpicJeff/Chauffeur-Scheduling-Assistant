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

# Hack trip_planner to print WHY a slot fails enforce_ideal_times=True
with open("services/trip_planner.py", "r") as f:
    code = f.read()

debug_code = """
            if enforce_ideal_times:
                s_slot = slot_local.time().hour * 60 + slot_local.time().minute
                e_slot = (slot_local + datetime.timedelta(minutes=poi.duration_mins)).time().hour * 60 + (slot_local + datetime.timedelta(minutes=poi.duration_mins)).time().minute
                s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
                e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute
                if s_slot == 1050:
                    print(f"Checking 17:30 EDT: s_slot={s_slot}, s_mins={s_mins}, e_mins={e_mins}")
                if s_slot < (s_mins - 15) or s_slot > (e_mins + 15):
                    continue
"""
code = code.replace(
"""
            if enforce_ideal_times:
                # Need to be within 15 minutes of the ideal time
                s_slot = slot_local.time().hour * 60 + slot_local.time().minute
                e_slot = (slot_local + datetime.timedelta(minutes=poi.duration_mins)).time().hour * 60 + (slot_local + datetime.timedelta(minutes=poi.duration_mins)).time().minute
                s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
                e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute
                if s_slot < (s_mins - 15) or s_slot > (e_mins + 15):
                    continue""", debug_code)

with open("services/trip_planner_hacked13.py", "w") as f:
    f.write(code)

sys.path.insert(0, ".")
import services.trip_planner_hacked13
services.trip_planner_hacked13.maps = services.trip_planner.maps
services.trip_planner_hacked13.calendar = sys.modules['services.calendar']

for p in trip.pois:
    if "Akershus" in p.name:
        print("Testing Akershus forced failure with EXACT mock_start_date and bounds=None...")
        p.valid_days_of_week = [0] # Monday
        res = services.trip_planner_hacked13.schedule_poi(trip, p, bounds=None)
        print("RESULT:", res)
