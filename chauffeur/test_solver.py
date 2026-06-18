from models.schemas import Event, Driver, Rule, PriorityRule
from solver.matcher import solve_schedule
from datetime import datetime, timedelta

def run_test():
    # Mock Drivers
    d1 = Driver(id="d1", name="Mom", color_code="#FF0000")
    d2 = Driver(id="d2", name="Dad", color_code="#0000FF")
    
    # Mock Events
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    e1 = Event(
        id="e1", title="Drop off Jimmy", 
        start=today + timedelta(hours=8), end=today + timedelta(hours=9), 
        location="School", calendar_ids=["c1"], source_event_ids=["c1::e1"]
    )
    e2 = Event(
        id="e2", title="Dentist Appointment", 
        start=today + timedelta(hours=8, minutes=30), end=today + timedelta(hours=9, minutes=30), 
        location="Dentist", calendar_ids=["c2"], source_event_ids=["c2::e2"]
    )
    
    # E3 is later, but travel time from E2 (Dentist -> Soccer) is 15 mins.
    # E2 ends at 9:30. E3 starts at 9:40. 9:40 - 9:30 = 10 mins < 15 mins + 5 min buffer.
    # So a driver cannot do E2 and E3 sequentially either!
    e3 = Event(
        id="e3", title="Soccer Practice", 
        start=today + timedelta(hours=9, minutes=40), end=today + timedelta(hours=11), 
        location="Soccer Field", calendar_ids=["c1"], source_event_ids=["c1::e3"]
    )
    
    # Mock Rules
    # Dad is required for Soccer Practice
    r1 = Rule(driver_id="d2", keywords=["Soccer"], constraint_type="required")
    # Mom is unavailable for Dentist
    r2 = Rule(driver_id="d1", keywords=["Dentist"], constraint_type="unavailable")
    
    # Let's add two fully conflicting events in the afternoon
    e4 = Event(
        id="e4", title="Low Priority Meeting", 
        start=today + timedelta(hours=14), end=today + timedelta(hours=15), 
        location="Office", calendar_ids=["c3"], source_event_ids=["c3::e4"]
    )
    e5 = Event(
        id="e5", title="CRITICAL Doctor Appointment", 
        start=today + timedelta(hours=14), end=today + timedelta(hours=15), 
        location="Hospital", calendar_ids=["c3"], source_event_ids=["c3::e5"]
    )
    # Passenger Overlap Test: Lily has two events at the exact same time
    e6 = Event(
        id="e6", title="Lily Piano", 
        start=today + timedelta(hours=16), end=today + timedelta(hours=17), 
        location="Piano Studio", calendar_ids=["lily"], source_event_ids=["lily::1"]
    )
    e7 = Event(
        id="e7", title="CRITICAL Lily Doctor", 
        start=today + timedelta(hours=16, minutes=30), end=today + timedelta(hours=17, minutes=30), 
        location="Clinic", calendar_ids=["lily"], source_event_ids=["lily::2"]
    )
    
    # Priority Rule: 'CRITICAL' gives +500 weight
    pr1 = PriorityRule(keywords=["CRITICAL"], weight_modifier=500)
    
    assignments, unassigned, _ = solve_schedule(
        events=[e1, e2, e3, e4, e5, e6, e7],
        drivers=[d1, d2],
        rules=[r1, r2],
        priority_rules=[pr1]
    )
    
    print("--- Solver Results ---")
    for e_id, d_id in assignments.items():
        print(f"Event {e_id} -> Driver {d_id}")
    print(f"Unassigned Events: {unassigned}")

if __name__ == "__main__":
    run_test()
