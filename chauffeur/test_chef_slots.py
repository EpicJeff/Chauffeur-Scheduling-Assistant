import json
import datetime
import zoneinfo
import sys
import unittest.mock as mock

from models.schemas import TripMetadata

# Mock storage to avoid file locks
sys.modules['services.storage'] = mock.MagicMock()

import services.trip_planner

db = json.load(open("data/db.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
# DO NOT OVERRIDE mock_start_date!

class MockEvent:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.id = "trip123"
        self.calendar_ids = ["dummy"]
trip.event_id = "trip123"

sys.modules['services.calendar'] = mock.MagicMock()
sys.modules['services.calendar'].get_events.return_value = [
    MockEvent(
        datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(trip.mock_end_date, tz=datetime.timezone.utc)
    )
]

services.trip_planner.calendar = sys.modules['services.calendar']

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

for p in trip.pois:
    if "Chef Mickey" in p.name:
        print("Testing Chef Mickey WITH BOUNDS...")
        
        # Manually step through the _find_slots logic for Chef Mickey
        duration_mins = p.duration_mins
        is_food = p.category == 'food'
        location = p.location
        bounds = (a_start, a_end)
        
        cals = []
        tz_str = trip.timeZone if trip.timeZone and trip.timeZone != "UTC" else "America/New_York"
        local_tz = zoneinfo.ZoneInfo(tz_str)
        
        trip_start = datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc)
        trip_end = datetime.datetime.fromtimestamp(trip.mock_end_date, tz=datetime.timezone.utc)
        trip_start = max(trip_start, bounds[0])
        trip_end = min(trip_end, bounds[1])
        
        duration_delta = datetime.timedelta(minutes=duration_mins)
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
        
        print(f"TRIP START: {trip_start}, END: {trip_end}, CURR: {curr}")
        
        while curr + duration_delta <= trip_end:
            slot_start = curr
            slot_end = curr + duration_delta
            curr += datetime.timedelta(minutes=15)
            
            slot_local = slot_start.astimezone(local_tz)
            slot_time = slot_local.time()
            s_slot = slot_time.hour * 60 + slot_time.minute
            
            s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
            e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute
            
            # Add a 15-minute grace period to the ideal window
            if s_slot < (s_mins - 15) or s_slot > (e_mins + 15):
                # print(f"Skipping {slot_time} because outside ideal window (s_slot={s_slot}, s_mins={s_mins}, e_mins={e_mins})")
                continue
                
            print(f"VALID SLOT FOUND: {slot_local}")
