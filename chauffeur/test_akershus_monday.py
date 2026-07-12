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

sys.modules['services.calendar'] = mock.MagicMock()
services.trip_planner.calendar = sys.modules['services.calendar']

# We don't care about calendar events, just overlapping events within the trip
sys.modules['services.calendar'].get_events.return_value = []

a_start = None
a_end = None
for p in trip.pois:
    if p.is_background and "Epcot" in p.name:
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)

print(f"EPCOT BOUNDS: {a_start} to {a_end}")

for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None
        
    if "Garden Grill" in p.name:
        # Schedule Garden Grill at 12:00 PM on the same day as EPCOT
        p.is_scheduled = True
        local_tz = zoneinfo.ZoneInfo("America/New_York")
        gg_start = a_start.astimezone(local_tz).replace(hour=12, minute=0, second=0)
        gg_end = gg_start + datetime.timedelta(minutes=p.duration_mins)
        p.scheduled_start = gg_start.timestamp()
        p.scheduled_end = gg_end.timestamp()

# Now test Akershus
for p in trip.pois:
    if "Akershus" in p.name:
        print("Testing Akershus...")
        p.valid_days_of_week = [0] # Set valid day to Monday
        
        cals = []
        local_tz = zoneinfo.ZoneInfo("America/New_York")
        
        trip_start = max(a_start, a_start) # Just use anchor bounds
        trip_end = min(a_end, a_end)
        
        duration_delta = datetime.timedelta(minutes=p.duration_mins)
        ideal_start_time = datetime.datetime.strptime(p.ideal_time_start, "%H:%M").time()
        ideal_end_time = datetime.time(21, 0)
        
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
            
            slot_local = slot_start.astimezone(local_tz)
            slot_time = slot_local.time()
            s_slot = slot_time.hour * 60 + slot_time.minute
            
            s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
            e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute
            
            if s_slot < (s_mins - 15) or s_slot > (e_mins + 15):
                continue
                
            print(f"VALID SLOT: {slot_local}")
            
            # Check for overlapping events (like Garden Grill)
            overlaps = False
            # Check meal conflict
            print(f"Checking {slot_local} for overlap/meal conflicts...")
