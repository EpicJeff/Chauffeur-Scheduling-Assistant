import sys
import datetime
sys.path.append('e:\\repositories\\Chauffeur\\chauffeur')
from solver.matcher import does_event_match_rule, get_grouped_event_pairs
from models.schemas import Rule, Event, Passenger, EventFilter

passengers = [
    Passenger(id="Lily", name="Lily"),
    Passenger(id="Nathan", name="Nathan")
]

rule = Rule(
    driver_id="Lorena",
    constraint_type="group",
    filter_sets=[
        EventFilter(keywords=["Warriors"]),
        EventFilter(keywords=["Torpedoes swim practice"])
    ]
)

events = [
    Event(id="e1", title="Warriors", start=datetime.datetime(2026,6,22,17,0), end=datetime.datetime(2026,6,22,18,30), location="The Lab", calendar_ids=[], source_event_ids=[]),
    Event(id="e2", title="Torpedoes swim practice", start=datetime.datetime(2026,6,22,18,15), end=datetime.datetime(2026,6,22,18,50), location="Ancient Oaks", calendar_ids=[], source_event_ids=[]),
    Event(id="e3", title="Torpedoes swim practice", start=datetime.datetime(2026,6,22,18,50), end=datetime.datetime(2026,6,22,19,30), location="Ancient Oaks", calendar_ids=[], source_event_ids=[])
]

for e in events:
    print(f"Event: {e.title}")
    match = does_event_match_rule(e, rule, passengers)
    print(f"  Matches rule? {match}")

pairs = get_grouped_event_pairs(events, [rule], passengers)
print(f"Pairs: {pairs}")
