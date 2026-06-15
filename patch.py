import os

content = open('chauffeur/solver/matcher.py', 'r').read()

r1 = '''def compute_route_edges(assignments: Dict[str, str], events: List[Event], drivers: List[Driver], home_location: Optional[str] = None, trip_metadata: List[dict] = None, driver_attendances: Dict[str, List[str]] = None, rules: List[Rule] = None, passengers: List[Passenger] = None) -> Tuple[Dict[str, dict], Dict[str, dict], Dict[str, dict]]:
    from collections import defaultdict
    driver_event_ids = defaultdict(set)'''
s1 = '''def compute_route_edges(assignments: Dict[str, str], events: List[Event], drivers: List[Driver], home_location: Optional[str] = None, trip_metadata: List[dict] = None, driver_attendances: Dict[str, List[str]] = None, rules: List[Rule] = None, passengers: List[Passenger] = None) -> Tuple[Dict[str, dict], Dict[str, dict], Dict[str, dict]]:
    from collections import defaultdict
    
    e_buffer_before = {}
    e_buffer_after = {}
    for e in events:
        bb = 0
        ba = 0
        if rules:
            for r in rules:
                if getattr(r, 'constraint_type', None) == 'buffer' and does_event_match_rule(e, r, passengers):
                    bb = max(bb, getattr(r, 'buffer_before_mins', 0))
                    ba = max(ba, getattr(r, 'buffer_after_mins', 0))
        e_buffer_before[e.id] = bb
        e_buffer_after[e.id] = ba
        
    driver_event_ids = defaultdict(set)'''
content = content.replace(r1, s1)

r2 = '''                        "to_event": first_ev.id,
                        "travel_mins": travel_to_pickup + travel_to_ev,
                        "delay_mins": delay_to_pickup + delay_to_ev,
                        "pickup_waypoint": {'''
s2 = '''                        "to_event": first_ev.id,
                        "travel_mins": travel_to_pickup + travel_to_ev,
                        "delay_mins": delay_to_pickup + delay_to_ev,
                        "buffer_before_mins": e_buffer_before.get(first_ev.id, 0),
                        "pickup_waypoint": {'''
content = content.replace(r2, s2)

r3 = '''                    initial_edges[d_id][first_ev.id] = {
                        "to_event": first_ev.id,
                        "travel_mins": travel,
                        "delay_mins": delay,
                        "driver_home_location": driver_home
                    }'''
s3 = '''                    initial_edges[d_id][first_ev.id] = {
                        "to_event": first_ev.id,
                        "travel_mins": travel,
                        "delay_mins": delay,
                        "buffer_before_mins": e_buffer_before.get(first_ev.id, 0),
                        "driver_home_location": driver_home
                    }'''
content = content.replace(r3, s3)

r4 = '''                    final_edges[d_id][last_ev.id] = {
                        "from_event": last_ev.id,
                        "travel_mins": travel_to_dropoff + travel_to_home,
                        "delay_mins": delay_to_dropoff + delay_to_home,
                        "dropoff_waypoint": {'''
s4 = '''                    final_edges[d_id][last_ev.id] = {
                        "from_event": last_ev.id,
                        "travel_mins": travel_to_dropoff + travel_to_home,
                        "delay_mins": delay_to_dropoff + delay_to_home,
                        "buffer_after_mins": e_buffer_after.get(last_ev.id, 0),
                        "dropoff_waypoint": {'''
content = content.replace(r4, s4)

r5 = '''                    final_edges[d_id][last_ev.id] = {
                        "from_event": last_ev.id,
                        "travel_mins": travel_home,
                        "delay_mins": delay_home,
                        "driver_home_location": driver_home_at_end
                    }'''
s5 = '''                    final_edges[d_id][last_ev.id] = {
                        "from_event": last_ev.id,
                        "travel_mins": travel_home,
                        "delay_mins": delay_home,
                        "buffer_after_mins": e_buffer_after.get(last_ev.id, 0),
                        "driver_home_location": driver_home_at_end
                    }'''
content = content.replace(r5, s5)

r6 = '''                edges[d_id][e1.id] = {
                    "to_event": e2.id,
                    "travel_mins": travel,
                    "delay_mins": delay,
                    "wait_mins": int(wait),
                    "late_mins": int(late)
                }'''
s6 = '''                edges[d_id][e1.id] = {
                    "to_event": e2.id,
                    "travel_mins": travel,
                    "delay_mins": delay,
                    "wait_mins": int(wait),
                    "late_mins": int(late),
                    "buffer_after_mins": e_buffer_after.get(e1.id, 0),
                    "buffer_before_mins": e_buffer_before.get(e2.id, 0)
                }'''
content = content.replace(r6, s6)

open('chauffeur/solver/matcher.py', 'w').write(content)
