import json
import datetime
import zoneinfo
import sys
import unittest.mock as mock

from models.schemas import TripMetadata, TripPOI

sys.modules['services.storage'] = mock.MagicMock()
import services.trip_planner

db = json.load(open("data/db.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
trip.is_draft = True

# Add 3 mock background POIs
trip.pois = []

b1 = TripPOI(id="b1", name="MK 1", location="Magic Kingdom", is_background=True, scheduled_start=1786622400.0, scheduled_end=1786676400.0)
b2 = TripPOI(id="b2", name="MK 2", location="Magic Kingdom", is_background=True, scheduled_start=1786708800.0, scheduled_end=1786762800.0)
b3 = TripPOI(id="b3", name="MK 3", location="Magic Kingdom", is_background=True, scheduled_start=1787054400.0, scheduled_end=1787108400.0)
trip.pois.extend([b1, b2, b3])

# Add 4 unconstrained POIs
p1 = TripPOI(id="p1", name="Ride 1", location="Magic Kingdom")
p2 = TripPOI(id="p2", name="Ride 2", location="Magic Kingdom")
p3 = TripPOI(id="p3", name="Ride 3", location="Magic Kingdom")
p4 = TripPOI(id="p4", name="Ride 4", location="Magic Kingdom")
trip.pois.extend([p1, p2, p3, p4])

# Mock the distance function so it returns 0 for Magic Kingdom
def mock_get_travel(origin, dest):
    if origin == "Magic Kingdom" and dest == "Magic Kingdom":
        return 0
    return 100

services.trip_planner.maps.get_travel_time_minutes = mock_get_travel
sys.modules['services.calendar'] = mock.MagicMock()
services.trip_planner.calendar = sys.modules['services.calendar']
services.trip_planner.schedule_poi = mock.MagicMock(return_value=("fake_id", None, None))

generator = services.trip_planner.schedule_pois_bulk(trip, ["p1", "p2", "p3", "p4"])
results = list(generator)

for res in results:
    if res["success"]:
        poi = next(p for p in trip.pois if p.id == res["poi_id"])
        print(f"Scheduled {poi.name}")

# Now look at how many are attached to each anchor cluster
print("Cluster sizes:")
# We need to hack into the local variables or recreate the logic to see the sizes...
# Actually we can just check what the generator returned, but the generator yields them in order of anchor.
# It should be 2 for b1, 1 for b2, 1 for b3.
