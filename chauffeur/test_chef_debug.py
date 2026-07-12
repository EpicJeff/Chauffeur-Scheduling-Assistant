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

mk3_bounds = None
for p in trip.pois:
    if p.is_background and "Magic Kingdom Park (Day 3)" in p.name:
        mk3_bounds = (
            datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc),
            datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)
        )

# Debug the exact constraints inside find_slots for Chef Mickey
for p in trip.pois:
    if "Chef Mickey" in p.name:
        print("Testing Chef Mickey...")
        
        cals = []
        local_tz = zoneinfo.ZoneInfo("America/New_York")
        
        trip_start = max(mk3_bounds[0], mk3_bounds[0])
        trip_end = min(mk3_bounds[1], mk3_bounds[1])
        
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
        
        print(f"TRIP START: {trip_start.astimezone(local_tz)}, END: {trip_end.astimezone(local_tz)}")
        print(f"DURATION: {duration_delta}")
        
        # Build overlapping events
        overlapping_events = []
        for other in trip.pois:
            if other.is_scheduled and other.id != p.id and other.scheduled_start:
                if getattr(other, 'is_background', False): continue
                
                class MockEvent:
                    def __init__(self, start, end, location):
                        self.start = start
                        self.end = end
                        self.location = location
                overlapping_events.append(MockEvent(
                    datetime.datetime.fromtimestamp(other.scheduled_start, tz=datetime.timezone.utc),
                    datetime.datetime.fromtimestamp(other.scheduled_end, tz=datetime.timezone.utc),
                    other.location
                ))
        
        is_food = p.category == 'food'
        
        while curr + duration_delta <= trip_end:
            slot_start = curr
            slot_end = curr + duration_delta
            curr += datetime.timedelta(minutes=15)
            
            slot_local = slot_start.astimezone(local_tz)
            slot_time = slot_local.time()
            s_slot = slot_time.hour * 60 + slot_time.minute
            
            # Print specifically around 17:00
            if 17 <= slot_time.hour <= 18:
                print(f"Checking {slot_time}...")
                
                s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
                e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute
                
                if s_slot < (s_mins - 15) or s_slot > (e_mins + 15):
                    print(f"  -> Failed ideal time bounds")
                    continue
                    
                overlaps = False
                for e in overlapping_events:
                    if not (slot_end <= e.start or slot_start >= e.end):
                        overlaps = True
                        print(f"  -> Overlaps with {e.start.astimezone(local_tz)} - {e.end.astimezone(local_tz)}")
                        break
                if overlaps: continue
                
                conflict = False
                if is_food:
                    slot_meal = "breakfast" if s_slot < 660 else "lunch" if s_slot < 960 else "dinner"
                    non_dessert_food = []
                    for e in overlapping_events:
                        if e.start.astimezone(local_tz).date() == slot_local.date():
                            e_s_slot = e.start.astimezone(local_tz).time().hour * 60 + e.start.astimezone(local_tz).time().minute
                            e_meal = "breakfast" if e_s_slot < 660 else "lunch" if e_s_slot < 960 else "dinner"
                            if e_meal == slot_meal:
                                non_dessert_food.append(e)
                    if len(non_dessert_food) > 0:
                        conflict = True
                        print(f"  -> Meal conflict! Found {len(non_dessert_food)} non-dessert food POIs in {slot_meal}.")
                if conflict: continue
                
                print(f"  -> VALID!")
