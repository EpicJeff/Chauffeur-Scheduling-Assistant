import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from models.schemas import Event
from solver.matcher import compute_route_edges
from datetime import datetime, timedelta
import json

e1 = Event(
    id="e1",
    title="Event 1",
    location="123 Origin St",
    start=datetime.now(),
    end=datetime.now() + timedelta(hours=1),
    calendar_ids=["cal1"]
)
e2 = Event(
    id="e2",
    title="Event 2",
    location="456 Dest St",
    start=datetime.now() + timedelta(hours=3),
    end=datetime.now() + timedelta(hours=4),
    calendar_ids=["cal2"]
)
e_pickup = Event(
    id="e_pickup",
    title="Pickup Event",
    location="789 Pickup St",
    start=datetime.now() - timedelta(hours=1),
    end=datetime.now() + timedelta(hours=1, minutes=30),
    calendar_ids=["cal2"]
)

assignments = {"e1": "d1", "e2": "d1"}
events = [e1, e2, e_pickup]
home_loc = "999 Home St"

edges = compute_route_edges(assignments, events, drivers=[], home_location=home_loc)
print(json.dumps(edges, indent=2))
