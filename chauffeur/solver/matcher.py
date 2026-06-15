from typing import List, Dict, Tuple, Optional
from ortools.sat.python import cp_model
from models.schemas import Event, Driver, Rule, PriorityRule, ManualOverride, Passenger
from services.maps import get_travel_time_minutes
from datetime import datetime
import math

def does_event_match_rule(event, rule, passengers=None) -> bool:
    has_any_criteria = False
    
    # 1. Keywords
    if hasattr(rule, 'keywords') and rule.keywords:
        has_any_criteria = True
        match_kw = False
        event_text = (event.title + " " + (event.description or "")).lower()
        for kw in rule.keywords:
            if kw.lower() in event_text:
                match_kw = True
                break
        if not match_kw: return False
        
    # 2. Passengers
    if hasattr(rule, 'passenger_ids') and rule.passenger_ids:
        has_any_criteria = True
        match_pax = False
        
        resolved_pids = set()
        for pid in rule.passenger_ids:
            resolved_pids.add(str(pid))
            if passengers:
                for p in passengers:
                    if pid == str(p.id) or (p.calendar_ids and pid in p.calendar_ids):
                        resolved_pids.add(str(p.id))
                        
        for pid in resolved_pids:
            if pid in event.calendar_ids:
                match_pax = True
                break
        if not match_pax: return False
        
    # 3. Days of Week
    if hasattr(rule, 'days_of_week') and rule.days_of_week:
        has_any_criteria = True
        if event.start.weekday() not in rule.days_of_week: return False
        
    # 4. Time Window
    if hasattr(rule, 'time_start') and rule.time_start:
        has_any_criteria = True
        try:
            h, m = map(int, rule.time_start.split(':'))
            if event.start.hour * 60 + event.start.minute < h * 60 + m: return False
        except: pass
        
    if hasattr(rule, 'time_end') and rule.time_end:
        has_any_criteria = True
        try:
            h, m = map(int, rule.time_end.split(':'))
            if event.end.hour * 60 + event.end.minute > h * 60 + m: return False
        except: pass
    # 5. Location
    if hasattr(rule, 'location') and rule.location:
        has_any_criteria = True
        if not event.location or rule.location.lower() not in event.location.lower():
            return False
            
    return has_any_criteria

def get_grouped_event_pairs(events: List[Event], rules: List[Rule], passengers: List[Passenger]) -> set:
    grouped_event_pairs = set()
    group_rules = [r for r in rules if getattr(r, 'constraint_type', None) == 'group']
    from collections import defaultdict
    for r in group_rules:
        daily_matches = defaultdict(list)
        for e in events:
            # Match any of the filter sets
            for fs in getattr(r, 'filter_sets', []):
                if does_event_match_rule(e, fs, passengers):
                    daily_matches[e.start.date()].append(e)
                    break
        for group_events in daily_matches.values():
            if len(group_events) > 1:
                for i in range(len(group_events)):
                    for j in range(i + 1, len(group_events)):
                        grouped_event_pairs.add((group_events[i].id, group_events[j].id))
                        grouped_event_pairs.add((group_events[j].id, group_events[i].id))
    return grouped_event_pairs

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
        
    # Default missing event locations to home_location to prevent 0-minute teleportation
    for e in events:
        if not getattr(e, 'location', None) or str(e.location).strip() == "":
            e.location = home_location

    # Pre-calculate requires_attendance per event
    req_att_cals = set(cal for p in passengers if p.requires_attendance for cal in p.calendar_ids)
    event_requires_attendance = {
        e.id: bool(set(e.calendar_ids).intersection(req_att_cals))
        for e in events
    }
        
    model = cp_model.CpModel()
    
    # 1. Variables: assign[e.id, d.id]
    assign_vars = {}
    assignable_events = [e for e in events if getattr(e, 'event_type', '') != 'background_trip']
    
    for e in assignable_events:
        for d in drivers:
            assign_vars[(e.id, d.id)] = model.NewBoolVar(f'assign_{e.id}_{d.id}')

    # 2. Constraint: Each event is assigned to AT MOST 1 driver
    for e in assignable_events:
        model.AddAtMostOne(assign_vars[(e.id, d.id)] for d in drivers)

    # 3. Constraint: No Overlap + Travel Time
    objective_terms = []
    
    e_tolerances = {}
    e_buffer_before = {}
    e_buffer_after = {}
    for e in assignable_events:
        tol = 0
        bb = 0
        ba = 0
        for r in rules:
            if does_event_match_rule(e, r, passengers):
                if r.constraint_type == 'tolerance':
                    tol = max(tol, getattr(r, 'tolerance_mins', 0))
                elif r.constraint_type == 'buffer':
                    bb = max(bb, getattr(r, 'buffer_before_mins', 0))
                    ba = max(ba, getattr(r, 'buffer_after_mins', 0))
        e_tolerances[e.id] = tol
        e_buffer_before[e.id] = bb
        e_buffer_after[e.id] = ba
        
    grouped_event_pairs = get_grouped_event_pairs(assignable_events, rules, passengers)

    # Sort events by start time to easily check pairs
    sorted_events = sorted(assignable_events, key=lambda x: x.start)
    for i in range(len(sorted_events)):
        for j in range(i + 1, len(sorted_events)):
            e1 = sorted_events[i]
            e2 = sorted_events[j]
            shares_calendar = bool(set(e1.calendar_ids).intersection(set(e2.calendar_ids)))
            
            if shares_calendar:
                travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                min_needed_seconds = (travel_time_mins + 5) * 60
                desired_needed_seconds = min_needed_seconds + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                
                # Check attendance constraints
                attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                
                gap_seconds_with_tolerance = gap_seconds + (e_tolerances.get(e2.id, 0) * 60)
                if gap_seconds_with_tolerance < min_needed_seconds:
                    # Passenger conflict hard penalty (impossible)
                    for d1 in drivers:
                        for d2 in drivers:
                            both = model.NewBoolVar(f'pass_conf_{e1.id}_{d1.id}_{e2.id}_{d2.id}')
                            model.AddImplication(both, assign_vars[(e1.id, d1.id)])
                            model.AddImplication(both, assign_vars[(e2.id, d2.id)])
                            model.AddBoolOr([both, assign_vars[(e1.id, d1.id)].Not(), assign_vars[(e2.id, d2.id)].Not()])
                            objective_terms.append(both * -2000000)
                elif gap_seconds < desired_needed_seconds:
                    # Passenger conflict soft penalty (buffer eaten into)
                    for d1 in drivers:
                        for d2 in drivers:
                            both = model.NewBoolVar(f'pass_buffer_conf_{e1.id}_{d1.id}_{e2.id}_{d2.id}')
                            model.AddImplication(both, assign_vars[(e1.id, d1.id)])
                            model.AddImplication(both, assign_vars[(e2.id, d2.id)])
                            model.AddBoolOr([both, assign_vars[(e1.id, d1.id)].Not(), assign_vars[(e2.id, d2.id)].Not()])
                            objective_terms.append(both * -50)
            else:
                travel_time_mins = get_switch_travel_time(e1, e2, events)
                min_needed_seconds = (travel_time_mins + 5) * 60
                desired_needed_seconds = min_needed_seconds + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                
                if e1.location and e2.location and e1.location.strip().lower() == e2.location.strip().lower():
                    gap_seconds = float('inf')
                else:
                    attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                    if not attendance_conflict and e1.location and e2.location:
                        req_d1_d2 = get_switch_travel_time(e1, e2, events) * 60
                        late_drop_e2 = max(0, req_d1_d2 - (e2.start - e1.start).total_seconds())
                        
                        # In profile overlap checks, we use min_needed_seconds strictly since it's already tight
                        req_e1_e2 = get_travel_time_minutes(e1.location, e2.location) * 60 + 5 * 60
                        req_e2_e1 = get_travel_time_minutes(e2.location, e1.location) * 60 + 5 * 60
                        
                        tol_e1 = e_tolerances.get(e1.id, 0) * 60
                        tol_e2 = e_tolerances.get(e2.id, 0) * 60
                        
                        if e2.end <= e1.end:
                            # Profile B: e2 is fully enveloped by e1. Drop e1 -> Drop e2 -> Pick e2 -> Pick e1
                            late_pick_e1 = max(0, req_e2_e1 - (e1.end - e2.end).total_seconds())
                            if late_drop_e2 <= tol_e2 and late_pick_e1 <= tol_e1:
                                gap_seconds = float('inf')
                        else:
                            # Profile A: e1 and e2 overlap. Drop e1 -> Drop e2 -> Pick e1 -> Pick e2
                            late_pick_e1 = max(0, req_e2_e1 - (e1.end - e2.start).total_seconds())
                            late_pick_e2 = max(0, req_e1_e2 - (e2.end - e1.end).total_seconds())
                            if late_drop_e2 <= tol_e2 and late_pick_e1 <= tol_e1 and late_pick_e2 <= tol_e2:
                                gap_seconds = float('inf')

                if (e1.id, e2.id) in grouped_event_pairs:
                    gap_seconds = float('inf')

                gap_seconds_with_tolerance = gap_seconds + (e_tolerances.get(e2.id, 0) * 60)
                if gap_seconds_with_tolerance < min_needed_seconds:
                    # Driver conflict hard penalty (impossible)
                    for d in drivers:
                        both = model.NewBoolVar(f'drv_conf_{e1.id}_{e2.id}_{d.id}')
                        model.AddImplication(both, assign_vars[(e1.id, d.id)])
                        model.AddImplication(both, assign_vars[(e2.id, d.id)])
                        model.AddBoolOr([both, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                        objective_terms.append(both * -1000000)
                elif gap_seconds < desired_needed_seconds:
                    # Driver conflict soft penalty (buffer eaten into)
                    for d in drivers:
                        both = model.NewBoolVar(f'drv_buffer_conf_{e1.id}_{e2.id}_{d.id}')
                        model.AddImplication(both, assign_vars[(e1.id, d.id)])
                        model.AddImplication(both, assign_vars[(e2.id, d.id)])
                        model.AddBoolOr([both, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                        objective_terms.append(both * -50)

    # 3b. Overridden pairs
    overridden_pairs = set((o.event_id, o.driver_id) for o in overrides)

    # 3c. Driver Personal Calendar Overlaps
    for d in drivers:
        d_events = driver_events.get(d.id, [])
        for e in assignable_events:
            for de in d_events:
                if getattr(de, 'event_type', '') == 'background_trip':
                    continue
                if e.id == de.id:
                    continue # Driver is an attendee of this event, do not block
                
                if e.location and de.location:
                    travel = get_travel_time_minutes(e.location, de.location)
                else:
                    travel = 20
                needed_secs_e_to_de = (travel + 5) * 60 + e_buffer_after.get(e.id, 0) * 60
                needed_secs_de_to_e = (travel + 5) * 60 + e_buffer_before.get(e.id, 0) * 60
                
                # Check for overlap
                e_before_de = (de.start - e.end).total_seconds() >= needed_secs_e_to_de
                de_before_e = (e.start - de.end).total_seconds() >= needed_secs_de_to_e
                
                if not e_before_de and not de_before_e:
                    # They physically overlap, driver cannot do this event
                    # Unavailability STRICTLY overrides pins
                    model.Add(assign_vars[(e.id, d.id)] == 0)

    # 4. Rules & Objective
    
    for e in assignable_events:
        # Calculate dynamic base weight for the event
        base_event_weight = 100
        for pr in priority_rules:
            mod = pr.weight_modifier
            if mod == 500 or mod == 200: mod = 10000
            elif mod == 100: mod = 1000
            elif mod == -100: mod = -1000
            elif mod == -500: mod = -10000
            
            if does_event_match_rule(e, pr, passengers):
                base_event_weight += mod
                
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
                if does_event_match_rule(e, r, passengers) and r.driver_id == d.id:
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
            
    # 4b. Passenger and Location Continuity Bonus
    for i in range(len(sorted_events)):
        for j in range(i + 1, len(sorted_events)):
            e1 = sorted_events[i]
            e2 = sorted_events[j]
            shares_calendar = bool(set(e1.calendar_ids).intersection(set(e2.calendar_ids)))
            same_loc = bool(e1.location and e2.location and e1.location.strip().lower() == e2.location.strip().lower())
            
            if e1.start.date() == e2.start.date():
                if shares_calendar or same_loc:
                    for d in drivers:
                        both_assigned = model.NewBoolVar(f'both_{e1.id}_{e2.id}_{d.id}')
                        model.AddImplication(both_assigned, assign_vars[(e1.id, d.id)])
                        model.AddImplication(both_assigned, assign_vars[(e2.id, d.id)])
                        model.AddBoolOr([both_assigned, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                        
                        if same_loc:
                            travel_mins = 0
                        else:
                            travel_mins = get_travel_time_minutes(e1.location, e2.location) if shares_calendar else get_switch_travel_time(e1, e2, events)
                        
                        if shares_calendar:
                            objective_terms.append(both_assigned * 50)
                            
                        if same_loc and travel_mins <= 5:
                            # Higher bonus for doing things at the exact same location (reduces travel)
                            objective_terms.append(both_assigned * 100)
                            
                        # Penalize travel time for events assigned to the same driver
                        gap_seconds = (e2.start - e1.end).total_seconds()
                        if gap_seconds < 10800: # 3 hours
                            objective_terms.append(both_assigned * (-int(travel_mins)))
                    
    # 4c. Mutually Exclusive Event Groups

    mut_ex_rules = [r for r in rules if r.constraint_type == 'mutually_exclusive']
    for r in mut_ex_rules:
        from collections import defaultdict
        groups = defaultdict(list)
        for e in assignable_events:
            if does_event_match_rule(e, r, passengers):
                period = getattr(r, 'grouping_period', 'daily')
                if period == 'daily':
                    key = (e.start.strftime('%Y-%m-%d'), r.id)
                elif period == 'weekly':
                    key = (e.start.strftime('%Y-%W'), r.id)
                elif period == 'monthly':
                    key = (e.start.strftime('%Y-%m'), r.id)
                else:
                    key = r.id
                groups[key].append(e)
                
        for key, group_events in groups.items():
            if len(group_events) > 1:
                group_vars = []
                for e in group_events:
                    for d in drivers:
                        group_vars.append(assign_vars[(e.id, d.id)])
                # Max 1 event from this group can be assigned
                model.Add(sum(group_vars) <= 1)

    # 4d. Custom Grouping Rules
    # Only iterate through unique pairs to save constraints (a, b) and avoid doing (b, a)
    processed_pairs = set()
    for e1_id, e2_id in grouped_event_pairs:
        pair_key = frozenset([e1_id, e2_id])
        if pair_key in processed_pairs:
            continue
        processed_pairs.add(pair_key)
        
        # Prevent splitting: if e1 is assigned to d1, e2 CANNOT be assigned to d2 (where d1 != d2).
        # This ensures that if both are assigned, they share the same driver.
        for d1 in drivers:
            for d2 in drivers:
                if d1.id != d2.id:
                    model.AddImplication(assign_vars[(e1_id, d1.id)], assign_vars[(e2_id, d2.id)].Not())

    # 4e. Override weights
    import time
    base_time = time.time()
    for o in overrides:
        if any(e.id == o.event_id for e in assignable_events):
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
        for e in assignable_events:
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
                        total_needed_seconds = (travel_time_mins + 5) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                        gap_seconds = (e2.start - e1.end).total_seconds()
                        if gap_seconds < total_needed_seconds:
                            mins_late = int((total_needed_seconds - gap_seconds) / 60)
                            # We attach the warning to e2 since it's the one they are arriving late to
                            lateness_warnings[e2.id] = f"Passenger will be {mins_late}m late (arriving from {e1.title})"
                    elif d1_id == d2_id:
                        travel_time_mins = get_switch_travel_time(e1, e2, events)
                        total_needed_seconds = (travel_time_mins + 5) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                        gap_seconds = (e2.start - e1.end).total_seconds()
                        if gap_seconds < total_needed_seconds:
                            mins_late = int((total_needed_seconds - gap_seconds) / 60)
                            if e2.id not in lateness_warnings: # Prioritize passenger warning if both exist
                                lateness_warnings[e2.id] = f"Driver will be {mins_late}m late (arriving from {e1.title})"
    else:
        # If infeasible (rare with soft assignments), all are unassigned
        unassigned = [e.id for e in events]
        
    return assignments, unassigned, lateness_warnings

def solve_ghost_routes(events: List[Event], assigned_events: List[Event] = None, rules: List[Rule] = None, passengers: List[Passenger] = None) -> Tuple[Dict[str, str], List[dict]]:
    if not events:
        return {}, []
        
    if assigned_events is None:
        assigned_events = []
    if rules is None:
        rules = []
    if passengers is None:
        passengers = []
        
    e_buffer_before = {}
    e_buffer_after = {}
    for e in events + assigned_events:
        bb = 0
        ba = 0
        for r in rules:
            if r.constraint_type == 'buffer' and does_event_match_rule(e, r, passengers):
                bb = max(bb, getattr(r, 'buffer_before_mins', 0))
                ba = max(ba, getattr(r, 'buffer_after_mins', 0))
        e_buffer_before[e.id] = bb
        e_buffer_after[e.id] = ba
        
    mut_ex_rules = [r for r in rules if r.constraint_type == 'mutually_exclusive']
    from collections import defaultdict
    mut_ex_counts = defaultdict(int)
    
    for r in mut_ex_rules:
        for ae in assigned_events:
            if does_event_match_rule(ae, r, passengers):
                period = getattr(r, 'grouping_period', 'daily')
                if period == 'daily':
                    key = (ae.start.strftime('%Y-%m-%d'), r.id)
                elif period == 'weekly':
                    key = (ae.start.strftime('%Y-%W'), r.id)
                elif period == 'monthly':
                    key = (ae.start.strftime('%Y-%m'), r.id)
                else:
                    key = r.id
                mut_ex_counts[key] += 1
    
    valid_events = []
    for e in events:
        is_impossible = False
        for ae in assigned_events:
            shares_calendar = bool(set(e.calendar_ids).intersection(set(ae.calendar_ids)))
            if shares_calendar:
                travel_time_mins = get_travel_time_minutes(e.location, ae.location)
                
                if e.start <= ae.start:
                    first, second = e, ae
                else:
                    first, second = ae, e
                total_needed_seconds = (travel_time_mins + 5) * 60 + e_buffer_after.get(first.id, 0) * 60 + e_buffer_before.get(second.id, 0) * 60    
                if (second.start - first.end).total_seconds() < total_needed_seconds:
                    is_impossible = True
                    break
                    
        if not is_impossible:
            for r in mut_ex_rules:
                if does_event_match_rule(e, r, passengers):
                    period = getattr(r, 'grouping_period', 'daily')
                    if period == 'daily':
                        key = (e.start.strftime('%Y-%m-%d'), r.id)
                    elif period == 'weekly':
                        key = (e.start.strftime('%Y-%W'), r.id)
                    elif period == 'monthly':
                        key = (e.start.strftime('%Y-%m'), r.id)
                    else:
                        key = r.id
                        
                    if mut_ex_counts[key] >= 1:
                        is_impossible = True
                        break
                    else:
                        mut_ex_counts[key] += 1
                        
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
                total_needed_seconds = (travel_time_mins + 5) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                if (e2.start - e1.end).total_seconds() < total_needed_seconds:
                    # Passenger conflict
                    is_assigned_e1 = sum(assign_vars[(e1.id, g_id)] for g_id in ghost_ids)
                    is_assigned_e2 = sum(assign_vars[(e2.id, g_id)] for g_id in ghost_ids)
                    model.Add(is_assigned_e1 + is_assigned_e2 <= 1)
            else:
                travel_time_mins = get_switch_travel_time(e1, e2, events)
                total_needed_seconds = (travel_time_mins + 5) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
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
        # If it ended within 15 minutes of e2.start
        if (e2.start - e_b_prev.end).total_seconds() <= 900:
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

def compute_route_edges(assignments: Dict[str, str], events: List[Event], drivers: List[Driver], home_location: Optional[str] = None, trip_metadata: List[dict] = None, driver_attendances: Dict[str, List[str]] = None, rules: List[Rule] = None, passengers: List[Passenger] = None) -> Tuple[Dict[str, dict], Dict[str, dict], Dict[str, dict]]:
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
    
    if trip_metadata is None: trip_metadata = []
    
    def get_active_home(entity_id: str, ts: float, default_home: str) -> str:
        for trip in trip_metadata:
            if entity_id in trip['entities'] or 'global' in trip['entities']:
                start_ts = trip['start'].timestamp()
                end_ts = trip['end'].timestamp()
                if start_ts <= ts <= end_ts:
                    return trip['location']
        return default_home

    def get_pax_id(cal_id: str) -> Optional[str]:
        if not passengers: return None
        for p in passengers:
            if cal_id == p.id or cal_id in p.calendar_ids:
                return p.id
        return None

    for d_id, evs in driver_events.items():
        evs.sort(key=lambda x: x.start)
        
        driver_default_home = home_location
        if d_id in driver_map and driver_map[d_id].home_location:
            driver_default_home = driver_map[d_id].home_location
            
        grouped_event_pairs = get_grouped_event_pairs(events, rules, passengers) if rules and passengers else set()
        
        # Group events by date to correctly compute initial edges per day and prevent cross-day routing
        from itertools import groupby
        for date_obj, date_evs_iter in groupby(evs, key=lambda x: x.start.date()):
            date_evs = list(date_evs_iter)
            if not date_evs:
                continue
                
            if driver_default_home and driver_default_home.strip() != "":
                first_ev = date_evs[0]
                is_passenger_ev = first_ev.id in assignments
                
                start_ts = first_ev.start.timestamp()
                driver_home = get_active_home(f'driver_{d_id}', start_ts, driver_default_home)
                global_home_at_start = get_active_home('global', start_ts, home_location)
                
                pax_home = global_home_at_start
                if is_passenger_ev:
                    for cid in first_ev.calendar_ids:
                        pid = get_pax_id(cid)
                        if pid:
                            pax_home = get_active_home(f'passenger_{pid}', start_ts, global_home_at_start)
                            break
                            
                if is_passenger_ev and pax_home and driver_home != pax_home:
                    travel_to_pickup, delay_to_pickup = get_travel_time_minutes(driver_home, pax_home, departure_time=int(start_ts), return_traffic=True)
                    travel_to_ev, delay_to_ev = get_travel_time_minutes(pax_home, first_ev.location, departure_time=int(start_ts), return_traffic=True)
                    initial_edges[d_id][first_ev.id] = {
                        "to_event": first_ev.id,
                        "travel_mins": travel_to_pickup + travel_to_ev,
                        "delay_mins": delay_to_pickup + delay_to_ev,
                        "buffer_before_mins": e_buffer_before.get(first_ev.id, 0),
                        "pickup_waypoint": {
                            "from_driver_home_mins": travel_to_pickup,
                            "from_global_home_mins": travel_to_ev,
                            "pickup_location": pax_home,
                            "driver_home_location": driver_home
                        }
                    }
                else:
                    travel, delay = get_travel_time_minutes(driver_home, first_ev.location, departure_time=int(start_ts), return_traffic=True)
                    initial_edges[d_id][first_ev.id] = {
                        "to_event": first_ev.id,
                        "travel_mins": travel,
                        "delay_mins": delay,
                        "buffer_before_mins": e_buffer_before.get(first_ev.id, 0),
                        "driver_home_location": driver_home
                    }
                
                last_ev = date_evs[-1]
                is_last_passenger_ev = last_ev.id in assignments
                
                end_ts = last_ev.end.timestamp()
                driver_home_at_end = get_active_home(f'driver_{d_id}', end_ts, driver_default_home)
                global_home_at_end = get_active_home('global', end_ts, home_location)
                
                pax_home = global_home_at_end
                if is_last_passenger_ev:
                    for cid in last_ev.calendar_ids:
                        pid = get_pax_id(cid)
                        if pid:
                            pax_home = get_active_home(f'passenger_{pid}', end_ts, global_home_at_end)
                            break
                            
                if is_last_passenger_ev and pax_home and driver_home_at_end != pax_home:
                    travel_to_dropoff, delay_to_dropoff = get_travel_time_minutes(last_ev.location, pax_home, departure_time=int(end_ts), return_traffic=True)
                    travel_to_home, delay_to_home = get_travel_time_minutes(pax_home, driver_home_at_end, departure_time=int(end_ts + travel_to_dropoff*60), return_traffic=True)
                    final_edges[d_id][last_ev.id] = {
                        "from_event": last_ev.id,
                        "travel_mins": travel_to_dropoff + travel_to_home,
                        "delay_mins": delay_to_dropoff + delay_to_home,
                        "buffer_after_mins": e_buffer_after.get(last_ev.id, 0),
                        "dropoff_waypoint": {
                            "to_global_home_mins": travel_to_dropoff,
                            "to_driver_home_mins": travel_to_home,
                            "dropoff_location": pax_home,
                            "driver_home_location": driver_home_at_end
                        }
                    }
                else:
                    travel_home, delay_home = get_travel_time_minutes(last_ev.location, driver_home_at_end, departure_time=int(end_ts), return_traffic=True)
                    final_edges[d_id][last_ev.id] = {
                        "from_event": last_ev.id,
                        "travel_mins": travel_home,
                        "delay_mins": delay_home,
                        "buffer_after_mins": e_buffer_after.get(last_ev.id, 0),
                        "driver_home_location": driver_home_at_end
                    }
                
            for i in range(len(date_evs) - 1):
                e1 = date_evs[i]
                e2 = date_evs[i+1]
                e1_cals = set(e1.calendar_ids)
                e2_cals = set(e2.calendar_ids)
                shares_calendar = bool(e1_cals.intersection(e2_cals))
                new_passengers = e2_cals - e1_cals
                if getattr(e2, 'event_type', 'standard') == 'pickup':
                    new_passengers = set()
                
                pickup_waypoint = None
                
                if (e1.id, e2.id) in grouped_event_pairs:
                    # They are grouped, so they are traveling together!
                    # The pickup for any new passengers is e1's location.
                    dep_time = min(e1.end.timestamp(), e2.start.timestamp())
                    drive_to_pickup = 0
                    delay_to = 0
                    
                    if e1.location and e2.location and e1.location.strip().lower() == e2.location.strip().lower():
                        drive_from_pickup, delay_from = 0, 0
                    else:
                        drive_from_pickup, delay_from = get_travel_time_minutes(e1.location, e2.location, departure_time=int(dep_time), return_traffic=True)
                    
                    pickup_waypoint = {
                        "to_pickup_mins": 0,
                        "from_pickup_mins": drive_from_pickup,
                        "pickup_location": e1.location,
                        "pickup_event_title": e1.title
                    }
                    travel = drive_from_pickup
                    delay = delay_from
                else:
                    # If e2 starts before e1 ends, we must depart from e1 right after dropoff (e1.start)
                    dep_time = min(e1.end.timestamp(), e2.start.timestamp())

                    if new_passengers:
                        assigned_events = [ev for ev in events if ev.id in assignments]
                        pickup_event = get_passenger_pickup_event_for_subset(e2, new_passengers, assigned_events)
                        if pickup_event:
                            pickup_location = pickup_event.location
                            pickup_title = pickup_event.title
                        else:
                            global_home_at_dep = get_active_home('global', dep_time, home_location)
                            pax_home = global_home_at_dep
                            if new_passengers:
                                for cid in new_passengers:
                                    pid = get_pax_id(cid)
                                    if pid:
                                        pax_home = get_active_home(f'passenger_{pid}', dep_time, global_home_at_dep)
                                        break
                                
                            driver_home_at_dep = get_active_home(f'driver_{d_id}', dep_time, driver_default_home)
                            pickup_location = pax_home if pax_home else driver_home_at_dep
                            pickup_title = "Home"
                            
                        drive_to_pickup, delay_to = get_travel_time_minutes(e1.location, pickup_location, departure_time=int(dep_time), return_traffic=True)
                        drive_from_pickup, delay_from = get_travel_time_minutes(pickup_location, e2.location, departure_time=int(dep_time + drive_to_pickup*60), return_traffic=True)
                        
                        pickup_waypoint = {
                            "to_pickup_mins": drive_to_pickup,
                            "from_pickup_mins": drive_from_pickup,
                            "pickup_location": pickup_location,
                            "pickup_event_title": pickup_title
                        }
                        travel = drive_to_pickup + drive_from_pickup
                        delay = delay_to + delay_from
                    else:
                        dep_time = min(e1.end.timestamp(), e2.start.timestamp())
                        drive_mins, delay_mins = get_travel_time_minutes(e1.location, e2.location, departure_time=int(dep_time), return_traffic=True)
                        travel = drive_mins
                        delay = delay_mins
                
                # Check for layover home trip (only if we have more than 45 mins of free time)
                
                # Wait time is calculated from arrival at e2.location until e2.start
                # But if they overlap, they might arrive exactly on time.
                arr_time = dep_time + (travel * 60)
                wait = max(0, (e2.start.timestamp() - arr_time) / 60)
            
                home_waypoint = None
                travel_gap = (e2.start.timestamp() - dep_time) / 60
                
                if pickup_waypoint:
                    next_dest = pickup_waypoint["pickup_location"]
                else:
                    next_dest = e2.location
                    
                driver_home_at_layover = get_active_home(f'driver_{d_id}', dep_time, driver_default_home)
                if (travel_gap > 45 or wait > 15) and driver_home_at_layover and driver_home_at_layover.strip() != "":
                    travel_to_home, to_delay = get_travel_time_minutes(e1.location, driver_home_at_layover, departure_time=int(dep_time), return_traffic=True)
                    travel_from_home, from_delay = get_travel_time_minutes(driver_home_at_layover, next_dest, departure_time=int(dep_time + travel_to_home*60), return_traffic=True)
                    
                    extra_drive = pickup_waypoint["from_pickup_mins"] if pickup_waypoint else 0
                    layover = travel_gap - travel_to_home - travel_from_home - extra_drive - 5
                    
                    if layover >= 20 or (wait > 15 and layover >= 0):
                        home_waypoint = {
                            "to_home_mins": travel_to_home,
                            "to_home_delay_mins": to_delay,
                            "from_home_mins": travel_from_home,
                            "from_home_delay_mins": from_delay,
                            "layover_mins": int(max(0, layover)),
                            "driver_home_location": driver_home_at_layover
                        }
                        travel = travel_to_home + travel_from_home + extra_drive
                        delay = to_delay + from_delay
                        # Arrive precisely on time
                        arr_time = dep_time + ((travel_to_home + max(0, layover) + travel_from_home + extra_drive) * 60)
                        wait = 0

                late = max(0, (arr_time - e2.start.timestamp()) / 60)
                
                ba = e_buffer_after.get(e1.id, 0)
                bb = e_buffer_before.get(e2.id, 0)
                slack = max(0, (e2.start.timestamp() - e1.end.timestamp()) / 60 - travel)
                if ba + bb > slack:
                    if ba + bb > 0:
                        actual_ba = int(slack * ba / (ba + bb))
                        actual_bb = int(slack * bb / (ba + bb))
                    else:
                        actual_ba = 0
                        actual_bb = 0
                else:
                    actual_ba = ba
                    actual_bb = bb

                edges[d_id][e1.id] = {
                    "to_event": e2.id,
                    "travel_mins": travel,
                    "delay_mins": delay,
                    "wait_mins": int(wait),
                    "late_mins": int(late),
                    "buffer_after_mins": actual_ba,
                    "buffer_before_mins": actual_bb
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
                    reason = {"text": "Blocked by Manual Override for another driver.", "type": "override"}
                if eid == e.id and did == 'unassigned':
                    reason = {"text": "Blocked by 'Unassigned' override.", "type": "override"}
                
            # 2. Driver Personal Calendar
            if not reason:
                for de in driver_events.get(d.id, []):
                    if e.id == de.id: continue
                    travel = get_travel_time_minutes(e.location, de.location) if e.location and de.location else 20
                    needed_secs = (travel + 5) * 60
                    e_before_de = (de.start - e.end).total_seconds() >= needed_secs
                    de_before_e = (e.start - de.end).total_seconds() >= needed_secs
                    if not e_before_de and not de_before_e:
                        if e.start <= de.start:
                            gap = (de.start - e.end).total_seconds()
                        else:
                            gap = (e.start - de.end).total_seconds()
                        e_duration = (e.end - e.start).total_seconds() / 60
                        lateness_mins = math.ceil((needed_secs - gap) / 60.0)
                        if lateness_mins > min(60, e_duration * 0.75):
                            lateness_mins = 0
                        reason = {
                            "text": f"Conflicts with driver's personal event: '{de.title}'",
                            "type": "personal_conflict",
                            "conflict_event_title": de.title,
                            "lateness_mins": lateness_mins if lateness_mins > 0 else None
                        }
                        break
                        
            # 2.5 Passenger Transit Check
            if not reason:
                e_cals = set(e.calendar_ids)
                for ae in events:
                    if getattr(ae, 'all_day', False): continue
                    if not getattr(ae, 'location', '') or not str(ae.location).strip(): continue
                    if ae.id == e.id: continue
                    if ae.start.date() != e.start.date(): continue
                    if e_cals.intersection(ae.calendar_ids):
                        travel = get_travel_time_minutes(e.location, ae.location) if e.location and ae.location else 20
                        needed_secs = (travel + 5) * 60
                        if e.start <= ae.start:
                            gap = (ae.start - e.end).total_seconds()
                        else:
                            gap = (e.start - ae.end).total_seconds()
                            
                        if gap < needed_secs:
                            e_duration = (e.end - e.start).total_seconds() / 60
                            lateness_mins = math.ceil((needed_secs - gap) / 60.0)
                            if lateness_mins > min(60, e_duration * 0.75):
                                lateness_mins = 0
                            reason = {
                                "text": f"Passenger cannot travel from/to '{ae.title}' in time.",
                                "type": "conflict",
                                "conflict_event_title": ae.title,
                                "lateness_mins": lateness_mins if lateness_mins > 0 else None
                            }
                            break
                            
            # 2.6 Driver Schedule Transit Check (Already Assigned Events)
            if not reason:
                for ae_id, assigned_d_id in assignments.items():
                    if assigned_d_id == d.id and ae_id != e.id:
                        ae = event_map.get(ae_id)
                        if not ae: continue
                        if ae.start.date() != e.start.date(): continue
                        
                        travel = get_travel_time_minutes(e.location, ae.location) if e.location and ae.location else 20
                        needed_secs = (travel + 5) * 60
                        if e.start <= ae.start:
                            gap = (ae.start - e.end).total_seconds()
                        else:
                            gap = (e.start - ae.end).total_seconds()
                            
                        if gap < needed_secs:
                            e_duration = (e.end - e.start).total_seconds() / 60
                            lateness_mins = math.ceil((needed_secs - gap) / 60.0)
                            if lateness_mins > min(60, e_duration * 0.75):
                                lateness_mins = 0
                            reason = {
                                "text": f"Driver cannot travel from/to scheduled event '{ae.title}' in time.",
                                "type": "conflict",
                                "conflict_event_title": ae.title,
                                "lateness_mins": lateness_mins if lateness_mins > 0 else None
                            }
                            break
                        
            # 3. Rule constraints
            if not reason:
                for r in rules:
                    if does_event_match_rule(e, r, passengers):
                        if r.constraint_type == 'unavailable' and r.driver_id == d.id:
                            reason = {"text": "Prohibited by 'Unavailable' rule.", "type": "rule"}
                            break
                        elif r.constraint_type == 'required' and r.driver_id != d.id:
                            if (e.id, d.id) not in overridden_pairs:
                                reason = {"text": "Blocked by 'Required' rule for another driver.", "type": "rule"}
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
                                if e.start <= a_e.start:
                                    gap_seconds = (a_e.start - e.end).total_seconds()
                                else:
                                    gap_seconds = (e.start - a_e.end).total_seconds()
                                e_duration = (e.end - e.start).total_seconds() / 60
                                lateness_mins = math.ceil((needed_secs - gap_seconds) / 60.0)
                                if lateness_mins > min(60, e_duration * 0.75):
                                    lateness_mins = 0
                                reason = {
                                    "text": f"Conflicts with assigned event: '{a_e.title}'",
                                    "type": "conflict",
                                    "conflict_event_id": a_e.id,
                                    "conflict_event_title": a_e.title,
                                    "lateness_mins": lateness_mins if lateness_mins > 0 else None
                                }
                                break

            if not reason:
                reason = {"text": "Dropped by solver to optimize overall schedule.", "type": "optimization"}
                
            diagnostics[u_id][d.id] = reason
            
    return diagnostics
            

def split_staggered_events(assignments: Dict[str, str], ghost_assignments: Dict[str, str], events: List[Event]) -> List[Event]:
    from collections import defaultdict
    driver_events = defaultdict(list)
    event_map = {e.id: e for e in events}
    
    all_assign = {**assignments, **ghost_assignments}
    for e_id, d_id in all_assign.items():
        if e_id in event_map:
            driver_events[d_id].append(event_map[e_id])
            
    events_to_remove = set()
    events_to_add = []
    
    for d_id, evs in driver_events.items():
        evs.sort(key=lambda x: x.start)
        
        # Detect staggers
        for i in range(len(evs) - 1):
            e1 = evs[i]
            e2 = evs[i+1]
            if e2.start < e1.end:
                # Overlap! Check if it's a valid stagger (i.e. not grouped, no shared calendar)
                shares_calendar = bool(set(e1.calendar_ids).intersection(set(e2.calendar_ids)))
                if not shares_calendar:
                    if e2.end <= e1.end:
                        # Profile B: e2 enveloped by e1. e1 is split, e2 is kept intact.
                        if e1.id not in events_to_remove:
                            events_to_remove.add(e1.id)
                            # Create e1 dropoff
                            e1_drop = e1.model_copy() if hasattr(e1, 'model_copy') else e1.copy()
                            e1_drop.id = e1.id + '_dropoff'
                            e1_drop.event_type = 'dropoff'
                            e1_drop.end = e1.start
                            events_to_add.append((e1_drop, d_id, e1.id in ghost_assignments))
                            
                            # Create e1 pickup
                            e1_pick = e1.model_copy() if hasattr(e1, 'model_copy') else e1.copy()
                            e1_pick.id = e1.id + '_pickup'
                            e1_pick.event_type = 'pickup'
                            e1_pick.start = e1.end
                            events_to_add.append((e1_pick, d_id, e1.id in ghost_assignments))
                    else:
                        # Profile A: e1 and e2 overlap. Both split.
                        if e1.id not in events_to_remove:
                            events_to_remove.add(e1.id)
                            e1_drop = e1.model_copy() if hasattr(e1, 'model_copy') else e1.copy()
                            e1_drop.id = e1.id + '_dropoff'
                            e1_drop.event_type = 'dropoff'
                            e1_drop.end = e1.start
                            events_to_add.append((e1_drop, d_id, e1.id in ghost_assignments))
                            
                            e1_pick = e1.model_copy() if hasattr(e1, 'model_copy') else e1.copy()
                            e1_pick.id = e1.id + '_pickup'
                            e1_pick.event_type = 'pickup'
                            e1_pick.start = e1.end
                            events_to_add.append((e1_pick, d_id, e1.id in ghost_assignments))
                            
                        if e2.id not in events_to_remove:
                            events_to_remove.add(e2.id)
                            e2_drop = e2.model_copy() if hasattr(e2, 'model_copy') else e2.copy()
                            e2_drop.id = e2.id + '_dropoff'
                            e2_drop.event_type = 'dropoff'
                            e2_drop.end = e2.start
                            events_to_add.append((e2_drop, d_id, e2.id in ghost_assignments))
                            
                            e2_pick = e2.model_copy() if hasattr(e2, 'model_copy') else e2.copy()
                            e2_pick.id = e2.id + '_pickup'
                            e2_pick.event_type = 'pickup'
                            e2_pick.start = e2.end
                            events_to_add.append((e2_pick, d_id, e2.id in ghost_assignments))

    if not events_to_remove:
        return events

    new_events = [e for e in events if e.id not in events_to_remove]
    for new_e, d_id, is_ghost in events_to_add:
        new_events.append(new_e)
        if is_ghost:
            ghost_assignments[new_e.id] = d_id
        else:
            assignments[new_e.id] = d_id
            
    for e_id in events_to_remove:
        if e_id in assignments:
            del assignments[e_id]
        if e_id in ghost_assignments:
            del ghost_assignments[e_id]
            
    return new_events

