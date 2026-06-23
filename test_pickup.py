import datetime
from chauffeur.models.schemas import Event
from chauffeur.solver import matcher

e1 = Event(
    id="torpedoes_nathan",
    title="Torpedoes",
    location="Torpedoes",
    start=datetime.datetime(2026, 6, 23, 18, 15),
    end=datetime.datetime(2026, 6, 23, 18, 50),
    calendar_ids=["nathan_cal"]
)

e2 = Event(
    id="torpedoes_lily",
    title="Torpedoes",
    location="Torpedoes",
    start=datetime.datetime(2026, 6, 23, 18, 50),
    end=datetime.datetime(2026, 6, 23, 19, 30),
    calendar_ids=["lily_cal"]
)

warriors = Event(
    id="warriors",
    title="Warriors",
    location="Warriors",
    start=datetime.datetime(2026, 6, 23, 17, 0),
    end=datetime.datetime(2026, 6, 23, 18, 30),
    calendar_ids=["lily_cal"]
)

events = [e1, e2, warriors]

pickup = matcher.get_passenger_pickup_event(e2, events)
print(f"Pickup event: {pickup.title if pickup else None}")

time = matcher.get_switch_travel_time(e1, e2, events)
print(f"Travel time: {time}")
