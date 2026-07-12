import json
from models.schemas import TripMetadata
import datetime
import zoneinfo
db = json.load(open("data/db_copy.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
trip.is_draft = True
trip.mock_start_date = int(datetime.datetime.now().timestamp())
trip.mock_end_date = trip.mock_start_date + (7 * 86400)

gg = next((p for p in trip.pois if "Garden Grill" in p.name), None)

# MOCK STORAGE
import sys
import unittest.mock as mock
mock_storage = mock.MagicMock()
mock_storage.get_settings.return_value = {"calendar_ids": ["dummy"]}
sys.modules['services.storage'] = mock_storage

from services.trip_planner import schedule_poi
gg.is_scheduled = False
gg.scheduled_start = None
gg.scheduled_end = None

# Let's override schedule_poi to print debug info from find_slots!
# Actually, I'll just copy find_slots logic here and run it to see exactly where it continues!

local_tz = zoneinfo.ZoneInfo("America/New_York")
trip_start = datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc)
trip_end = datetime.datetime.fromtimestamp(trip.mock_end_date, tz=datetime.timezone.utc)

ideal_start_time = datetime.time(17, 0)
ideal_end_time = datetime.time(21, 0)
duration_delta = datetime.timedelta(minutes=90)
poi = gg

curr = trip_start
while curr + duration_delta <= trip_end:
    slot_start = curr
    slot_end = curr + duration_delta
    curr += datetime.timedelta(minutes=15)
    
    slot_local = slot_start.astimezone(local_tz)
    slot_time = slot_local.time()
    
    if slot_local.weekday() == 3 and slot_time.hour == 17 and slot_time.minute == 0:
        print(f"Testing 17:00 on Thursday!")
        
        # Check all constraints
        earliest_time = datetime.time(7, 0)
        print(f"earliest_time check: {slot_time < earliest_time}")
        
        print(f"valid_days check: {slot_local.weekday() not in poi.valid_days_of_week}")
        
        s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
        e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute
        s_slot = slot_time.hour * 60 + slot_time.minute
        
        print(f"ideal_time check: s_slot={s_slot}, s_mins={s_mins}, e_mins={e_mins}. Failed? {s_slot < (s_mins - 15) or s_slot > (e_mins + 15)}")
