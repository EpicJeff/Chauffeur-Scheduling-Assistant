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
    return slots

services.trip_planner._find_slots = debug_find_slots

tz = zoneinfo.ZoneInfo("America/New_York")
a_start = None
a_end = None
for p in trip.pois:
    if p.is_background and "Day 3" in p.name:
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None

# monkeypatch trip_planner to print out the reject reason
with open("services/trip_planner.py", "r") as f:
    code = f.read()

# I will just write a custom script that does the find_slots logic to see what fails
def find_why_fails():
    bounds = (a_start, a_end)
    poi = next(p for p in trip.pois if "Chef Mickey" in p.name)
    trip_start = a_start
    trip_end = a_end
    duration_delta = datetime.timedelta(minutes=poi.duration_mins)
    
    ideal_start_time = datetime.datetime.strptime(poi.ideal_time_start, "%H:%M").time()
    ideal_end_time = datetime.time(21, 0)
    
    s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
    e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute
    
    curr = trip_start
    discard_mins = curr.minute % 15
    if discard_mins > 0:
        if discard_mins >= 8:
            curr += datetime.timedelta(minutes=(15 - discard_mins))
        else:
            curr -= datetime.timedelta(minutes=discard_mins)
    curr = curr.replace(second=0, microsecond=0)

    while curr + duration_delta <= trip_end:
        slot_start = curr
        slot_end = curr + duration_delta
        curr += datetime.timedelta(minutes=15)
        
        slot_local = slot_start.astimezone(tz)
        slot_time = slot_local.time()
        
        if slot_time.hour == 17 and slot_time.minute == 15:
            print("TESTING 17:15")
            
            earliest_time = datetime.time(7, 0)
            if slot_time < earliest_time:
                print("Failed earliest_time")
                
            slot_end_local = slot_end.astimezone(tz)
            if getattr(poi, 'valid_days_of_week', None):
                if slot_local.weekday() not in poi.valid_days_of_week:
                    print(f"Failed valid_days: {slot_local.weekday()} not in {poi.valid_days_of_week}")
                    
            s_slot = slot_time.hour * 60 + slot_time.minute
            e_slot = slot_end_local.hour * 60 + slot_end_local.minute
            
            if s_slot < (s_mins - 15) or s_slot > (e_mins + 15):
                print(f"Failed ideal_times: s_slot={s_slot}, s_mins={s_mins}")
            if e_slot > (e_mins + 120):
                print("Failed ideal_times end")

find_why_fails()

