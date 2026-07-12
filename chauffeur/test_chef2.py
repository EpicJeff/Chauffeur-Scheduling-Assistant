import json
from models.schemas import TripMetadata
import datetime
import zoneinfo
import sys

db = json.load(open("data/db.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
tz = zoneinfo.ZoneInfo("America/New_York")

a_start = None
a_end = None
for p in trip.pois:
    if p.is_background and "Day 3" in p.name:
        p.is_scheduled = True
        a_start = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        a_end = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)

chef = next(p for p in trip.pois if "Chef Mickey" in p.name)

# manual find_slots logic
duration_delta = datetime.timedelta(minutes=chef.duration_mins)
ideal_start_time = datetime.datetime.strptime(chef.ideal_time_start, "%H:%M").time()
ideal_end_time = datetime.time(21, 0)
s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute

curr = a_start
discard_mins = curr.minute % 15
if discard_mins > 0:
    if discard_mins >= 8:
        curr += datetime.timedelta(minutes=(15 - discard_mins))
    else:
        curr -= datetime.timedelta(minutes=discard_mins)
curr = curr.replace(second=0, microsecond=0)

while curr + duration_delta <= a_end:
    slot_start = curr
    slot_end = curr + duration_delta
    curr += datetime.timedelta(minutes=15)
    
    slot_local = slot_start.astimezone(tz)
    slot_time = slot_local.time()
    slot_end_local = slot_end.astimezone(tz)
    
    s_slot = slot_time.hour * 60 + slot_time.minute
    e_slot = slot_end_local.hour * 60 + slot_end_local.minute
    
    if s_slot < (s_mins - 15) or s_slot > (e_mins + 15):
        continue
    if e_slot > (e_mins + 120):
        continue
        
    print(f"VALID SLOT: {slot_local} to {slot_end_local}")
