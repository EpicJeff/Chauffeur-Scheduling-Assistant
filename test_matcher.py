import sys
import datetime
sys.path.append('e:\\repositories\\Chauffeur\\chauffeur')
from models.schemas import Event, Passenger, Rule, EventFilter
from solver.matcher import get_grouped_event_pairs, does_event_match_rule

p1 = Passenger(id="PaxA", name="PaxA")
p2 = Passenger(id="PaxB", name="PaxB")

e1 = Event(id="E1", title="Event 1", start=datetime.datetime(2026, 6, 22, 10), end=datetime.datetime(2026, 6, 22, 11), location="Loc1", calendar_ids=["PaxA"])
e2 = Event(id="E2", title="Event 2", start=datetime.datetime(2026, 6, 22, 11), end=datetime.datetime(2026, 6, 22, 12), location="Loc2", calendar_ids=["PaxB"])

rule = Rule(
    driver_id="driver1",
    constraint_type="group",
    filter_sets=[
        EventFilter(passenger_ids=["PaxA"]),
        EventFilter(passenger_ids=["PaxB"])
    ]
)

print("E1 Match rule directly:", does_event_match_rule(e1, rule, [p1, p2]))
print("E2 Match rule directly:", does_event_match_rule(e2, rule, [p1, p2]))

groups = get_grouped_event_pairs([e1, e2], [rule], [p1, p2])
print("Groups:", groups)
