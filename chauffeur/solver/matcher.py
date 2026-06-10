from typing import List, Dict, Tuple, Optional
from ortools.sat.python import cp_model
from models.schemas import Event, Driver, Rule, PriorityRule, ManualOverride, Passenger
from services.maps import get_travel_time_minutes
from datetime import datetime

def solve_schedule(
    events: List[Event],
    drivers: List[Driver],
    rules: List[Rule],
    priority_rules: List[PriorityRule] = None,
    overrides: List[ManualOverride] = None,
    previous_assignments: Dict[str, str] = None,
    driver_events: Dict[str, List[Event]] = None,
    passengers: List[Passenger] = None
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
    if passengers is None:
        passengers = []
        
    # Pre-calculate requires_attendance per event
    req_att_cals = set(cal for p in passengers if p.requires_attendance for cal in p.calendar_ids)
    event_requires_attendance = {
        e.id: bool(set(e.calendar_ids).intersection(req_att_cals))
        for e in events
    }
        
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
                
                # Check attendance constraints
                attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                # If neither requires attendance, and we can perform interleaved dropoffs/pickups:
                # D1 -> D2 -> P1 -> P2
                # Dropoff gap: e2.start - e1.start >= travel(e1.location, e2.location)
                # Pickup gap: e2.end - e1.end >= travel(e1.location, e2.location)
                # This is a simplification. A full simulation is better.
                if not attendance_conflict:
                    # Let's see if we can do D1 -> e2_pickup -> D2
                    d1_to_d2 = get_travel_time_minutes(e1.location, e2.location) * 60
                    if (e2.start - e1.start).total_seconds() >= d1_to_d2 and (e2.end - e1.end).total_seconds() >= d1_to_d2:
                        gap_seconds = float('inf')  # Allow overlap!

                if gap_seconds < total_needed_seconds:
                    # Passenger conflict soft penalty
                    for d1 in drivers:
                        for d2 in drivers:
                            both = model.NewBoolVar(f'pass_conf_{e1.id}_{d1.id}_{e2.id}_{d2.id}')
                            model.AddImplication(both, assign_vars[(e1.id, d1.id)])
                            model.AddImplication(both, assign_vars[(e2.id, d2.id)])
                            model.AddBoolOr([both, assign_vars[(e1.id, d1.id)].Not(), assign_vars[(e2.id, d2.id)].Not()])
                            objective_terms.append(both * -2000000)
            else:
                travel_time_mins = get_switch_travel_time(e1, e2, events)
                total_needed_seconds = (travel_time_mins + 5) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                
                attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                if not attendance_conflict:
                    # e1 and e2 do not share a calendar, meaning e2 passengers need pickup
                    d1_to_d2 = get_switch_travel_time(e1, e2, events) * 60
                    if (e2.start - e1.start).total_seconds() >= d1_to_d2 and (e2.end - e1.end).total_seconds() >= get_travel_time_minutes(e1.location, e2.location) * 60:
                        gap_seconds = float('inf')

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
        if any(e.id == o.event_id for e in events):
            if o.driver_id == 'unassigned':
                for d in drivers:
                    model.Add(assign_vars[(o.event_id, d.id)] == 0)
            elif any(d.id == o.driver_id for d in drivers):
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

def get_passenger_pickup_event_for_subset(e2: Event, subset_cals: set, all_events: List[Event]) -> Optional[Event]:
    b_events = [e for e in all_events if e.id != e2.id and set(e.calendar_ids).intersection(subset_cals)]
    b_events_before = [e for e in b_events if e.end <= e2.start and e.start.date() == e2.start.date()]
    
    if b_events_before:
        e_b_prev = max(b_events_before, key=lambda x: x.end)
        # If it ended within 2 hours of e2.start
        if (e2.start - e_b_prev.end).total_seconds() <= 7200:
            return e_b_prev
    return None

def get_passenger_pickup_event(e2: Event, all_events: List[Event]) -> Optional[Event]:
    return get_passenger_pickup_event_for_subset(e2, set(e2.calendar_ids), all_events)

def get_switch_travel_time(e1: Event, e2: Event, all_events: List[Event]) -> int:
    pickup = get_passenger_pickup_event(e2, all_events)
    if pickup:
        t1 = get_travel_time_minutes(e1.location, pickup.location)
        t2 = get_travel_time_minutes(pickup.location, e2.location)
        return t1 + t2
    # Default 30 min buffer
    return get_travel_time_minutes(e1.location, e2.location) + 30

def compute_route_edges(assignments: Dict[str, str], events: List[Event], drivers: List[Driver], home_location: Optional[str] = None, driver_attendances: Dict[str, List[str]] = None) -> Tuple[Dict[str, dict], Dict[str, dict], Dict[str, dict]]:
    from collections import defaultdict
    driver_event_ids = defaultdict(set)
    event_map = {e.id: e for e in events}
    
    for e_id, d_id in assignments.items():
        if e_id in event_map:
            driver_event_ids[d_id].add(e_id)
            
    if driver_attendances:
        for d_id, e_ids in driver_attendances.items():
            for e_id in e_ids:
                if e_id in event_map:
                    driver_event_ids[d_id].add(e_id)
                    
    # Convert sets back to lists for sorting
    driver_events = {d_id: [event_map[e_id] for e_id in ev_ids] for d_id, ev_ids in driver_event_ids.items()}
            
    edges = defaultdict(dict)
    initial_edges = defaultdict(dict)
    final_edges = defaultdict(dict)
    driver_map = {d.id: d for d in drivers}
    
    for d_id, evs in driver_events.items():
        evs.sort(key=lambda x: x.start)
        
        # Determine the driver's specific home location
        driver_home = home_location
        if d_id in driver_map and driver_map[d_id].home_location:
            driver_home = driver_map[d_id].home_location
            
        # Group events by date to correctly compute initial edges per day and prevent cross-day routing
        from itertools import groupby
        for date_obj, date_evs_iter in groupby(evs, key=lambda x: x.start.date()):
            date_evs = list(date_evs_iter)
            if not date_evs:
                continue
                
            if driver_home and driver_home.strip() != "":
                first_ev = date_evs[0]
                is_passenger_ev = first_ev.id in assignments
                
                if is_passenger_ev and home_location and driver_home != home_location:
                    travel_to_pickup, delay_to_pickup = get_travel_time_minutes(driver_home, home_location, departure_time=int(first_ev.start.timestamp()), return_traffic=True)
                    travel_to_ev, delay_to_ev = get_travel_time_minutes(home_location, first_ev.location, departure_time=int(first_ev.start.timestamp()), return_traffic=True)
                    initial_edges[d_id][first_ev.id] = {
                        "to_event": first_ev.id,
                        "travel_mins": travel_to_pickup + travel_to_ev,
                        "delay_mins": delay_to_pickup + delay_to_ev,
                        "pickup_waypoint": {
                            "from_driver_home_mins": travel_to_pickup,
                            "from_global_home_mins": travel_to_ev
                        }
                    }
                else:
                    travel, delay = get_travel_time_minutes(driver_home, first_ev.location, departure_time=int(first_ev.start.timestamp()), return_traffic=True)
                    initial_edges[d_id][first_ev.id] = {
                        "to_event": first_ev.id,
                        "travel_mins": travel,
                        "delay_mins": delay
                    }
                
                last_ev = date_evs[-1]
                is_last_passenger_ev = last_ev.id in assignments
                
                if is_last_passenger_ev and home_location and driver_home != home_location:
                    travel_to_dropoff, delay_to_dropoff = get_travel_time_minutes(last_ev.location, home_location, departure_time=int(last_ev.end.timestamp()), return_traffic=True)
                    travel_to_home, delay_to_home = get_travel_time_minutes(home_location, driver_home, departure_time=int(last_ev.end.timestamp() + travel_to_dropoff*60), return_traffic=True)
                    final_edges[d_id][last_ev.id] = {
                        "from_event": last_ev.id,
                        "travel_mins": travel_to_dropoff + travel_to_home,
                        "delay_mins": delay_to_dropoff + delay_to_home,
                        "dropoff_waypoint": {
                            "to_global_home_mins": travel_to_dropoff,
                            "to_driver_home_mins": travel_to_home
                        }
                    }
                else:
                    travel_home, delay_home = get_travel_time_minutes(last_ev.location, driver_home, departure_time=int(last_ev.end.timestamp()), return_traffic=True)
                    final_edges[d_id][last_ev.id] = {
                        "from_event": last_ev.id,
                        "travel_mins": travel_home,
                        "delay_mins": delay_home
                    }
                
            for i in range(len(date_evs) - 1):
                e1 = date_evs[i]
                e2 = date_evs[i+1]
                e1_cals = set(e1.calendar_ids)
                e2_cals = set(e2.calendar_ids)
                shares_calendar = bool(e1_cals.intersection(e2_cals))
                new_passengers = e2_cals - e1_cals
                
                pickup_waypoint = None
                
                if new_passengers:
                    pickup_event = get_passenger_pickup_event_for_subset(e2, new_passengers, events)
                    if pickup_event:
                        pickup_location = pickup_event.location
                        pickup_title = pickup_event.title
                    else:
                        pickup_location = home_location if home_location else driver_home
                        pickup_title = "Home"
                    
                    # If e2 starts before e1 ends, we must depart from e1 right after dropoff (e1.start)
                    dep_time = min(e1.end.timestamp(), e2.start.timestamp())
                    
                    drive_to_pickup, delay_to = get_travel_time_minutes(e1.location, pickup_location, departure_time=int(dep_time), return_traffic=True)
                    drive_from_pickup, delay_from = get_travel_time_minutes(pickup_location, e2.location, departure_time=int(dep_time + drive_to_pickup*60), return_traffic=True)
                    
                    travel = drive_to_pickup + drive_from_pickup
                    delay = delay_to + delay_from
                    next_origin = pickup_location
                    
                    pickup_waypoint = {
                        "to_pickup_mins": drive_to_pickup,
                        "from_pickup_mins": drive_from_pickup,
                        "pickup_location": pickup_location,
                        "pickup_event_title": pickup_title
                    }
                else:
                    dep_time = min(e1.end.timestamp(), e2.start.timestamp())
                    travel, delay = get_travel_time_minutes(e1.location, e2.location, departure_time=int(dep_time), return_traffic=True)
                    next_origin = e2.location
                    pickup_event = None
                    
                # Wait time is calculated from arrival at e2.location until e2.start
                # But if they overlap, they might arrive exactly on time.
                arr_time = dep_time + (travel * 60)
                wait = max(0, (e2.start.timestamp() - arr_time) / 60)
            
                home_waypoint = None
                travel_gap = (e2.start.timestamp() - dep_time) / 60
                pickup_location = pickup_event.location if (not shares_calendar and pickup_event) else e2.location
                if travel_gap > 45 and driver_home and driver_home.strip() != "":
                    travel_to_home, to_delay = get_travel_time_minutes(e1.location, driver_home, departure_time=int(dep_time), return_traffic=True)
                    travel_from_home, from_delay = get_travel_time_minutes(driver_home, pickup_location, departure_time=int(dep_time + travel_to_home*60), return_traffic=True)
                    layover = travel_gap - travel_to_home - travel_from_home
                    
                    if layover >= 20:
                        home_waypoint = {
                            "to_home_mins": travel_to_home,
                            "to_home_delay_mins": to_delay,
                            "from_home_mins": travel_from_home,
                            "from_home_delay_mins": from_delay,
                            "layover_mins": int(layover)
                        }
                        travel = travel_to_home + travel_from_home
                        delay = to_delay + from_delay
                
                edges[d_id][e1.id] = {
                    "to_event": e2.id,
                    "travel_mins": travel,
                    "delay_mins": delay,
                    "wait_mins": int(wait)
                }
                if pickup_waypoint:
                    edges[d_id][e1.id]["pickup_waypoint"] = pickup_waypoint
                if home_waypoint:
                    edges[d_id][e1.id]["home_waypoint"] = home_waypoint

    return edges, initial_edges, final_edges

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

def compute_diagnostics(unassigned_ids: List[str], events: List[Event], drivers: List[Driver], driver_events: dict, assignments: dict, overrides: List[dict], rules: List[Rule], passengers: List[Passenger] = None) -> dict:
    if passengers is None:
        passengers = []
        
    req_att_cals = set(cal for p in passengers if p.requires_attendance for cal in p.calendar_ids)
    event_requires_attendance = {
        e.id: bool(set(e.calendar_ids).intersection(req_att_cals))
        for e in events
    }
    
    diagnostics = {}
    event_map = {e.id: e for e in events}
    overridden_pairs = set()
    for o in overrides:
        eid = getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None)
        did = getattr(o, 'driver_id', o.get('driver_id') if isinstance(o, dict) else None)
        if eid and did:
            overridden_pairs.add((eid, did))
    
    for u_id in unassigned_ids:
        e = event_map.get(u_id)
        if not e: continue
        
        diagnostics[u_id] = {}
        for d in drivers:
            reason = None
            
            # 1. Overrides
            for o in overrides:
                eid = getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None)
                did = getattr(o, 'driver_id', o.get('driver_id') if isinstance(o, dict) else None)
                if eid == e.id and did != d.id and did != 'unassigned':
                    reason = "Blocked by Manual Override for another driver."
                if eid == e.id and did == 'unassigned':
                    reason = "Blocked by 'Unassigned' override."
                
            # 2. Driver Personal Calendar
            if not reason:
                for de in driver_events.get(d.id, []):
                    if e.id == de.id: continue
                    travel = get_travel_time_minutes(e.location, de.location) if e.location and de.location else 20
                    needed_secs = (travel + 5) * 60
                    e_before_de = (de.start - e.end).total_seconds() >= needed_secs
                    de_before_e = (e.start - de.end).total_seconds() >= needed_secs
                    if not e_before_de and not de_before_e:
                        reason = f"Conflicts with driver's personal event: '{de.title}'"
                        break
                        
            # 3. Rule constraints
            if not reason:
                for r in rules:
                    if r.event_keyword.lower() in e.title.lower():
                        if r.constraint_type == 'unavailable' and r.driver_id == d.id:
                            reason = "Prohibited by 'Unavailable' rule."
                            break
                        elif r.constraint_type == 'required' and r.driver_id != d.id:
                            if (e.id, d.id) not in overridden_pairs:
                                reason = "Blocked by 'Required' rule for another driver."
                                break
            
            # 4. Overlap with existing assignments
            if not reason:
                for a_id, a_d_id in assignments.items():
                    if a_d_id == d.id and a_id != e.id:
                        a_e = event_map.get(a_id)
                        if a_e:
                            shares_calendar = bool(set(e.calendar_ids).intersection(set(a_e.calendar_ids)))
                            if shares_calendar:
                                travel = get_travel_time_minutes(e.location, a_e.location) if e.location and a_e.location else 20
                            else:
                                travel = get_switch_travel_time(e, a_e, events)
                            needed_secs = (travel + 5) * 60
                            e_before_a = (a_e.start - e.end).total_seconds() >= needed_secs
                            a_before_e = (e.start - a_e.end).total_seconds() >= needed_secs
                            
                            attendance_conflict = event_requires_attendance.get(e.id, False) or event_requires_attendance.get(a_e.id, False)
                            allow_overlap = False
                            if not attendance_conflict:
                                d1_to_d2 = get_travel_time_minutes(e.location, a_e.location) * 60
                                if e.start <= a_e.start:
                                    if (a_e.start - e.start).total_seconds() >= d1_to_d2 and (a_e.end - e.end).total_seconds() >= d1_to_d2:
                                        allow_overlap = True
                                else:
                                    if (e.start - a_e.start).total_seconds() >= d1_to_d2 and (e.end - a_e.end).total_seconds() >= d1_to_d2:
                                        allow_overlap = True
                                        
                            if not e_before_a and not a_before_e and not allow_overlap:
                                reason = f"Conflicts with assigned event: '{a_e.title}'"
                                break

            if not reason:
                reason = "Dropped by solver to optimize overall schedule."
                
            diagnostics[u_id][d.id] = reason
            
    return diagnostics
