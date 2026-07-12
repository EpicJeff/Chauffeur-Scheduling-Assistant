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

epcot_bounds = None
for p in trip.pois:
    if p.is_background and "Epcot" in p.name:
        epcot_bounds = (
            datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc),
            datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)
        )
trip.mock_start_date = epcot_bounds[0].timestamp()
trip.mock_end_date = epcot_bounds[1].timestamp()

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
    MockEvent(epcot_bounds[0], epcot_bounds[1])
]
trip.event_id = "trip123"

# Find Garden grill
for p in trip.pois:
    if "Garden Grill" in p.name:
        print("Garden Grill bounds:", p.scheduled_start, p.scheduled_end)

for p in trip.pois:
    if "Akershus" in p.name:
        print("Testing Akershus overlap logic...")
        
        cals = []
        local_tz = zoneinfo.ZoneInfo("America/New_York")
        
        # Build overlapping events
        overlapping_events = []
        for other in trip.pois:
            if other.is_scheduled and other.id != p.id and other.scheduled_start:
                p_is_bg = getattr(other, 'is_background', False)
                if getattr(p, 'is_background', False):
                    if not p_is_bg: continue
                else:
                    if p_is_bg: continue
                    
                class MockEv:
                    def __init__(self, start, end, location):
                        self.start = start
                        self.end = end
                        self.location = location
                overlapping_events.append(MockEv(
                    datetime.datetime.fromtimestamp(other.scheduled_start, tz=datetime.timezone.utc),
                    datetime.datetime.fromtimestamp(other.scheduled_end, tz=datetime.timezone.utc),
                    other.location
                ))
        
        print(f"Total overlapping events: {len(overlapping_events)}")
        
        # Test 12:00 PM EDT (which is 16:00 UTC)
        slot_start = datetime.datetime(2026, 8, 17, 16, 0, tzinfo=datetime.timezone.utc)
        slot_end = slot_start + datetime.timedelta(minutes=p.duration_mins)
        
        print(f"Testing slot: {slot_start.astimezone(local_tz)} to {slot_end.astimezone(local_tz)}")
        
        overlaps = False
        for e in overlapping_events:
            if not (slot_end <= e.start or slot_start >= e.end):
                overlaps = True
                print(f"  -> Overlaps with {e.start.astimezone(local_tz)} - {e.end.astimezone(local_tz)}")
                break
        
        if overlaps:
            print("Successfully caught overlap!")
        else:
            print("FAIL: Did NOT catch overlap!")
