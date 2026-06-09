from typing import List, Dict, Tuple, Optional
from ortools.sat.python import cp_model
from models.schemas import Event, Driver, Rule, PriorityRule, ManualOverride
from services.maps import get_travel_time_minutes
from datetime import datetime

def solve_schedule(
    events: List[Event],
    drivers: List[Driver],
    rules: List[Rule],
    priority_rules: List[PriorityRule] = None,
    overrides: List[ManualOverride] = None,
    previous_assignments: Dict[str, str] = None,
    driver_events: Dict[str, List[Event]] = None
) -> Tuple[Dict[str, str], List[str]]:
    """
    Solves the driver assignment problem using OR-Tools CP-SAT solver.
    Returns:
        assignments: Dict mapping event_id -> driver_id
        unassigned: List of event_ids that could not be assigned
    """
    if previous_assignments is None:
        previous_assignments = {}
    if priority_rules is None:
        priority_rules = []
    if overrides is None:
        overrides = []
    if driver_events is None:
        driver_events = {}

    model = cp_model.CpModel()
    
    # 1. Variables: assign[e.id, d.id]
    assign_vars = {}
    for e in events:
        for d in drivers:
            assign_vars[(e.id, d.id)] = model.NewBoolVar(f'assign_{e.id}_{d.id}')

    # 2. Constraint: Each event is assigned to AT MOST 1 driver
    for e in events:
        model.AddAtMostOne(assign_vars[(e.id, d.id)] for d in drivers)

    # 3. Constraint: No Overlap + Travel Time
    objective_terms = []
    
    # Sort events by start time to easily check pairs
    sorted_events = sorted(events, key=lambda x: x.start)
    for i in range(len(sorted_events)):
        for j in range(i + 1, len(sorted_events)):
            e1 = sorted_events[i]
            e2 = sorted_events[j]
            shares_calendar = bool(set(e1.calendar_ids).intersection(set(e2.calendar_ids)))
            
            if shares_calendar:
                travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                total_needed_seconds = (travel_time_mins + 5) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                if gap_seconds < total_needed_seconds:
                    # Passenger conflict soft penalty
                    for d1 in drivers:
                        for d2 in drivers:
                            both = model.NewBoolVar(f'pass_conf_{e1.id}_{d1.id}_{e2.id}_{d2.id}')
                            model.AddImplication(both, assign_vars[(e1.id, d1.id)])
                            model.AddImplication(both, assign_vars[(e2.id, d2.id)])
                            model.AddBoolOr([both, assign_vars[(e1.id, d1.id)].Not(), assign_vars[(e2.id, d2.id)].Not()])
                            objective_terms.append(both * -1000000)
            else:
                travel_time_mins = get_switch_travel_time(e1, e2, events)
                total_needed_seconds = (travel_time_mins + 5) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                if gap_seconds < total_needed_seconds:
                    # Driver conflict soft penalty
                    for d in drivers:
                        both = model.NewBoolVar(f'drv_conf_{e1.id}_{e2.id}_{d.id}')
                        model.AddImplication(both, assign_vars[(e1.id, d.id)])
                        model.AddImplication(both, assign_vars[(e2.id, d.id)])
                        model.AddBoolOr([both, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                        objective_terms.append(both * -1000000)

    # 3b. Overridden pairs
    overridden_pairs = set((o.event_id, o.driver_id) for o in overrides)

    # 3c. Driver Personal Calendar Overlaps
    for d in drivers:
        d_events = driver_events.get(d.id, [])
        for e in events:
            for de in d_events:
                if e.id == de.id:
                    continue # Driver is an attendee of this event, do not block
                
                if e.location and de.location:
                    travel = get_travel_time_minutes(e.location, de.location)
                else:
                    travel = 20
                needed_secs = (travel + 5) * 60
                
                # Check for overlap
                e_before_de = (de.start - e.end).total_seconds() >= needed_secs
                de_before_e = (e.start - de.end).total_seconds() >= needed_secs
                
                if not e_before_de and not de_before_e:
                    # They physically overlap, driver cannot do this event
                    # Unavailability STRICTLY overrides pins
                    model.Add(assign_vars[(e.id, d.id)] == 0)

    # 4. Rules & Objective
    
    for e in events:
        # Calculate dynamic base weight for the event
        base_event_weight = 100
        for pr in priority_rules:
            if pr.match_type == 'keyword' and pr.match_value.lower() in e.title.lower():
                base_event_weight += pr.weight_modifier
            elif pr.match_type == 'calendar' and pr.match_value in e.calendar_ids:
                base_event_weight += pr.weight_modifier
                
        for d in drivers:
            weight = base_event_weight
            
            # Huge bonus if driver is an attendee of the event
            if any(de.id == e.id for de in driver_events.get(d.id, [])):
                weight += 2000

            
            # Group weight
            if d.group == 'primary':
                weight += 500
            elif d.group == 'secondary':
                weight += 100
                
            # Priority within group (lower index = higher priority)
            weight += max(0, (10 - d.priority_index) * 10)
            
            # Preferred hours penalty
            if d.preferred_start and d.preferred_end:
                try:
                    p_start = datetime.strptime(d.preferred_start, '%H:%M').time()
                    p_end = datetime.strptime(d.preferred_end, '%H:%M').time()
                    
                    e_start_time = e.start.time()
                    e_end_time = e.end.time()
                    
                    if e_start_time < p_start or e_end_time > p_end:
                        weight -= 300
                except ValueError:
                    pass
            
            # Stickiness
            if previous_assignments.get(e.id) == d.id:
                weight += 20
                
            # Apply Driver Rules
            for r in rules:
                # Simple keyword matching (case-insensitive)
                if r.event_keyword.lower() in e.title.lower() and r.driver_id == d.id:
                    if r.constraint_type == 'required':
                        # This driver MUST do it, meaning all other drivers cannot
                        for other_d in drivers:
                            if other_d.id != d.id:
                                if (e.id, other_d.id) not in overridden_pairs:
                                    model.Add(assign_vars[(e.id, other_d.id)] == 0)
                        weight += 500
                    elif r.constraint_type == 'preferred':
                        weight += 200
                    elif r.constraint_type == 'unavailable':
                        model.Add(assign_vars[(e.id, d.id)] == 0)
                        
            objective_terms.append(assign_vars[(e.id, d.id)] * weight)
            
    # 4b. Passenger Continuity Bonus
    for i in range(len(sorted_events)):
        for j in range(i + 1, len(sorted_events)):
            e1 = sorted_events[i]
            e2 = sorted_events[j]
            shares_calendar = bool(set(e1.calendar_ids).intersection(set(e2.calendar_ids)))
            
            if shares_calendar and e1.start.date() == e2.start.date():
                for d in drivers:
                    both_assigned = model.NewBoolVar(f'both_{e1.id}_{e2.id}_{d.id}')
                    model.AddImplication(both_assigned, assign_vars[(e1.id, d.id)])
                    model.AddImplication(both_assigned, assign_vars[(e2.id, d.id)])
                    model.AddBoolOr([both_assigned, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                    # Add a nice bonus for keeping a passenger with the same driver across multiple events on the SAME DAY
                    objective_terms.append(both_assigned * 50)
                    
    # 4c. Override weights
    import time
    base_time = time.time()
    for o in overrides:
        if any(e.id == o.event_id for e in events) and any(d.id == o.driver_id for d in drivers):
            # Calculate weight: Base 1,000,000 + seconds since override was created
            # This ensures newer overrides always win over older ones if they conflict
            try:
                # If created_at is not present (old overrides), default to 0
                created_at = getattr(o, 'created_at', 0)
                time_weight = int(created_at) if created_at else 0
            except:
                time_weight = 0
            objective_terms.append(assign_vars[(o.event_id, o.driver_id)] * (1000000 + time_weight))
            
    # Maximize total score
    model.Maximize(sum(objective_terms))
    
    # 5. Solve
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    assignments = {}
    unassigned = []
    
    lateness_warnings = {}
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        for e in events:
            assigned = False
            for d in drivers:
                if solver.BooleanValue(assign_vars[(e.id, d.id)]):
                    assignments[e.id] = d.id
                    assigned = True
                    break
            if not assigned:
                unassigned.append(e.id)
                
        # Calculate actual lateness for the final assigned schedule
        for i in range(len(sorted_events)):
            for j in range(i + 1, len(sorted_events)):
                e1 = sorted_events[i]
                e2 = sorted_events[j]
                d1_id = assignments.get(e1.id)
                d2_id = assignments.get(e2.id)
                
                if d1_id and d2_id:
                    shares_calendar = bool(set(e1.calendar_ids).intersection(set(e2.calendar_ids)))
                    if shares_calendar:
                        travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                        total_needed_seconds = (travel_time_mins + 5) * 60
                        gap_seconds = (e2.start - e1.end).total_seconds()
                        if gap_seconds < total_needed_seconds:
                            mins_late = int((total_needed_seconds - gap_seconds) / 60)
                            # We attach the warning to e2 since it's the one they are arriving late to
                            lateness_warnings[e2.id] = f"Passenger will be {mins_late}m late (arriving from {e1.title})"
                    elif d1_id == d2_id:
                        travel_time_mins = get_switch_travel_time(e1, e2, events)
                        total_needed_seconds = (travel_time_mins + 5) * 60
                        gap_seconds = (e2.start - e1.end).total_seconds()
                        if gap_seconds < total_needed_seconds:
                            mins_late = int((total_needed_seconds - gap_seconds) / 60)
                            if e2.id not in lateness_warnings: # Prioritize passenger warning if both exist
                                lateness_warnings[e2.id] = f"Driver will be {mins_late}m late (arriving from {e1.title})"
    else:
        # If infeasible (rare with soft assignments), all are unassigned
        unassigned = [e.id for e in events]
        
    return assignments, unassigned, lateness_warnings

def solve_ghost_routes(events: List[Event], assigned_events: List[Event] = None) -> Tuple[Dict[str, str], List[dict]]:
    if not events:
        return {}, []
        
    if assigned_events is None:
        assigned_events = []
    
    valid_events = []
    for e in events:
        is_impossible = False
        for ae in assigned_events:
            shares_calendar = bool(set(e.calendar_ids).intersection(set(ae.calendar_ids)))
            if shares_calendar:
                travel_time_mins = get_travel_time_minutes(e.location, ae.location)
                total_needed_seconds = (travel_time_mins + 5) * 60
                
                if e.start <= ae.start:
                    first, second = e, ae
                else:
                    first, second = ae, e
                    
                if (second.start - first.end).total_seconds() < total_needed_seconds:
                    is_impossible = True
                    break
        if not is_impossible:
            valid_events.append(e)
            
    events = valid_events
    
    if not events:
        return {}, []
    
    num_ghosts = len(events)
    ghost_ids = [f"ghost_{i+1}" for i in range(num_ghosts)]
    
    model = cp_model.CpModel()
    
    assign_vars = {}
    for e in events:
        for g_id in ghost_ids:
            assign_vars[(e.id, g_id)] = model.NewBoolVar(f'assign_{e.id}_{g_id}')
            
    for e in events:
        model.AddExactlyOne(assign_vars[(e.id, g_id)] for g_id in ghost_ids)
                        
    sorted_events = sorted(events, key=lambda x: x.start)
    for i in range(len(sorted_events)):
        for j in range(i + 1, len(sorted_events)):
            e1 = sorted_events[i]
            e2 = sorted_events[j]
            shares_calendar = bool(set(e1.calendar_ids).intersection(set(e2.calendar_ids)))
            
            if shares_calendar:
                travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                total_needed_seconds = (travel_time_mins + 5) * 60
                if (e2.start - e1.end).total_seconds() < total_needed_seconds:
                    # Passenger conflict
                    is_assigned_e1 = sum(assign_vars[(e1.id, g_id)] for g_id in ghost_ids)
                    is_assigned_e2 = sum(assign_vars[(e2.id, g_id)] for g_id in ghost_ids)
                    model.Add(is_assigned_e1 + is_assigned_e2 <= 1)
            else:
                travel_time_mins = get_switch_travel_time(e1, e2, events)
                total_needed_seconds = (travel_time_mins + 5) * 60
                if (e2.start - e1.end).total_seconds() < total_needed_seconds:
                    # Driver conflict
                    for g_id in ghost_ids:
                        model.AddImplication(assign_vars[(e1.id, g_id)], assign_vars[(e2.id, g_id)].Not())
                    
    used_vars = {}
    for g_id in ghost_ids:
        used_vars[g_id] = model.NewBoolVar(f'used_{g_id}')
        for e in events:
            model.AddImplication(assign_vars[(e.id, g_id)], used_vars[g_id])
            
    objective_terms = []
    for i, g_id in enumerate(ghost_ids):
        objective_terms.append(used_vars[g_id] * (1000 + i))
        
    model.Minimize(sum(objective_terms))
    
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    assignments = {}
    used_ghost_ids = set()
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        for e in events:
            for g_id in ghost_ids:
                if solver.BooleanValue(assign_vars[(e.id, g_id)]):
                    assignments[e.id] = g_id
                    used_ghost_ids.add(g_id)
                    break
                    
    ghost_drivers = []
    id_mapping = {}
    counter = 1
    for g_id in sorted(list(used_ghost_ids), key=lambda x: int(x.split('_')[1])):
        new_id = f"g{counter}"
        id_mapping[g_id] = new_id
        ghost_drivers.append({
            "id": new_id,
            "name": f"Suggested Route {counter}",
            "color_code": "#8B5CF6"
        })
        counter += 1
        
    final_assignments = {e_id: id_mapping[g_id] for e_id, g_id in assignments.items()}
    return final_assignments, ghost_drivers

def get_passenger_pickup_event(e2: Event, all_events: List[Event]) -> Optional[Event]:
    e2_cals = set(e2.calendar_ids)
    b_events = [e for e in all_events if e.id != e2.id and set(e.calendar_ids).intersection(e2_cals)]
    b_events_before = [e for e in b_events if e.end <= e2.start and e.start.date() == e2.start.date()]
    
    if b_events_before:
        e_b_prev = max(b_events_before, key=lambda x: x.end)
        # If it ended within 2 hours of e2.start
        if (e2.start - e_b_prev.end).total_seconds() <= 7200:
            return e_b_prev
    return None

def get_switch_travel_time(e1: Event, e2: Event, all_events: List[Event]) -> int:
    pickup = get_passenger_pickup_event(e2, all_events)
    if pickup:
        t1 = get_travel_time_minutes(e1.location, pickup.location)
        t2 = get_travel_time_minutes(pickup.location, e2.location)
        return t1 + t2
    # Default 30 min buffer
    return get_travel_time_minutes(e1.location, e2.location) + 30

def compute_route_edges(assignments: Dict[str, str], events: List[Event], home_location: Optional[str] = None) -> Dict[str, dict]:
    from collections import defaultdict
    driver_events = defaultdict(list)
    event_map = {e.id: e for e in events}
    
    for e_id, d_id in assignments.items():
        if e_id in event_map:
            driver_events[d_id].append(event_map[e_id])
            
    edges = {}
    for d_id, evs in driver_events.items():
        evs.sort(key=lambda x: x.start)
        for i in range(len(evs) - 1):
            e1 = evs[i]
            e2 = evs[i+1]
            shares_calendar = bool(set(e1.calendar_ids).intersection(set(e2.calendar_ids)))
            
            pickup_waypoint = None
            if shares_calendar:
                travel = get_travel_time_minutes(e1.location, e2.location)
                next_origin = e1.location
                drive_to_pickup = 0
                drive_from_pickup = travel
            else:
                travel = get_switch_travel_time(e1, e2, events)
                pickup_event = get_passenger_pickup_event(e2, events)
                if pickup_event:
                    next_origin = pickup_event.location
                    drive_to_pickup = get_travel_time_minutes(e1.location, pickup_event.location)
                    drive_from_pickup = get_travel_time_minutes(pickup_event.location, e2.location)
                    pickup_waypoint = {
                        "to_pickup_mins": drive_to_pickup,
                        "from_pickup_mins": drive_from_pickup,
                        "pickup_location": pickup_event.location,
                        "pickup_event_title": pickup_event.title
                    }
                else:
                    next_origin = e1.location
                    drive_to_pickup = 0
                    drive_from_pickup = travel
                
            wait = max(0, (e2.start - e1.end).total_seconds() / 60 - travel)
            
            home_waypoint = None
            if home_location and home_location.strip() != "":
                # Check if layover at home is possible
                drive_to_home = get_travel_time_minutes(e1.location, home_location)
                drive_from_home = get_travel_time_minutes(home_location, next_origin)
                layover_mins = (e2.start - e1.end).total_seconds() / 60 - drive_to_home - drive_from_home - drive_from_pickup
                
                # If we have 15 mins or more to stay at home
                if layover_mins >= 15:
                    home_waypoint = {
                        "to_home_mins": drive_to_home,
                        "from_home_mins": drive_from_home,
                        "layover_mins": int(layover_mins)
                    }
            
            edges[e1.id] = {
                "to_event": e2.id,
                "travel_mins": travel,
                "wait_mins": int(wait)
            }
            if pickup_waypoint:
                edges[e1.id]["pickup_waypoint"] = pickup_waypoint
            if home_waypoint:
                edges[e1.id]["home_waypoint"] = home_waypoint

    return edges

def compute_conflicts(assignments: Dict[str, str], ghost_assignments: Dict[str, str], events: List[Event]) -> Dict[str, List[dict]]:
    from collections import defaultdict
    conflicts = defaultdict(list)
    event_map = {e.id: e for e in events}
    
    assigned_events = [event_map[e_id] for e_id in assignments.keys() if e_id in event_map]
    ghost_events = [event_map[e_id] for e_id in ghost_assignments.keys() if e_id in event_map]
    
    for a_ev in assigned_events:
        for g_ev in ghost_events:
            travel = get_travel_time_minutes(a_ev.location, g_ev.location)
            needed_secs = (travel + 5) * 60
            
            a_before_g = (g_ev.start - a_ev.end).total_seconds() >= needed_secs
            g_before_a = (a_ev.start - g_ev.end).total_seconds() >= needed_secs
            
            if not a_before_g and not g_before_a:
                conflicts[a_ev.id].append({
                    "event_id": g_ev.id,
                    "title": g_ev.title
                })
                
    return conflicts
