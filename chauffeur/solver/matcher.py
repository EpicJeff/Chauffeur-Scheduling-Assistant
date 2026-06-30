from typing import List, Dict, Tuple, Optional
from ortools.sat.python import cp_model
from models.schemas import Event, Driver, Rule, PriorityRule, ManualOverride, Passenger
from services.maps import get_travel_time_minutes as _raw_get_travel_time_minutes

def get_travel_time_minutes(origin, dest, departure_time=None, return_traffic=False):
    if return_traffic:
        t, d = _raw_get_travel_time_minutes(origin, dest, departure_time, True)
        if t <= 3:
            return 0, 0
        return t, d
    else:
        t = _raw_get_travel_time_minutes(origin, dest, departure_time, False)
        if t <= 3:
            return 0
        return t

from datetime import datetime, time, timedelta
import math

def get_event_passenger_ids(event, passengers):
    if not passengers: return set()
    result = set()
    e_cals = set(event.calendar_ids)
    for p in passengers:
        if str(p.id) in e_cals:
            result.add(p.id)
        elif set(p.calendar_ids).intersection(e_cals):
            result.add(p.id)
    return result

def get_effective_overridden_event_ids(events, overrides) -> list:
    overridden_ids = set()
    sorted_overrides = sorted(overrides, key=lambda x: getattr(x, 'created_at', x.get('created_at', 0) if isinstance(x, dict) else 0) or 0, reverse=True)
    for e in events:
        instance_o = next((o for o in sorted_overrides if (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.id)), None)
        original_o = next((o for o in sorted_overrides if getattr(e, 'original_event_id', None) and (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.original_event_id)), None)
        series_o = next((o for o in sorted_overrides if getattr(e, 'recurring_event_id', None) and (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.recurring_event_id)), None)
        
        if instance_o or original_o or series_o:
            overridden_ids.add(e.id)
            
    for o in overrides:
        eid = getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None)
        if eid:
            overridden_ids.add(eid)
            
    return list(overridden_ids)


def get_active_home(entity_id: str, ts: float, default_home: str, trip_metadata: List[dict] = None) -> str:
    if not trip_metadata: return default_home
    for trip in trip_metadata:
        if entity_id in trip['entities'] or 'global' in trip['entities']:
            start_ts = trip['start'].timestamp()
            end_ts = trip['end'].timestamp()
            if start_ts <= ts <= end_ts:
                return trip['location']
    return default_home

def does_event_match_rule(event, rule, passengers=None) -> bool:
    if getattr(rule, 'constraint_type', '') == 'group':
        if hasattr(rule, 'filter_sets') and rule.filter_sets:
            for fs in rule.filter_sets:
                if does_event_match_rule(event, fs, passengers):
                    return True
        return False
        
    has_top_criteria = False
    top_matches = True
    
    # 1. Keywords
    if hasattr(rule, 'keywords') and rule.keywords:
        has_top_criteria = True
        event_text = (event.title + " " + (event.description or "")).lower()
        match_all = getattr(rule, 'keywords_match_all', False)
        
        if match_all:
            match_kw = True
            for kw in rule.keywords:
                if kw.lower() not in event_text:
                    match_kw = False
                    break
        else:
            match_kw = False
            for kw in rule.keywords:
                if kw.lower() in event_text:
                    match_kw = True
                    break
                    
        if not match_kw: top_matches = False
        
    # 2. Passengers
    raw_pids = getattr(rule, 'passenger_ids', []) or []
    if not isinstance(raw_pids, list): raw_pids = [raw_pids]
    extra_pax = getattr(rule, 'passengers', None)
    if extra_pax:
        if isinstance(extra_pax, list): raw_pids.extend(extra_pax)
        elif isinstance(extra_pax, str): raw_pids.append(extra_pax)
        
    if top_matches and raw_pids:
        has_top_criteria = True
        match_all = getattr(rule, 'passengers_match_all', False)
        
        if match_all:
            match_pax = True
            for pid in raw_pids:
                resolved_pids_for_this_passenger = {str(pid)}
                if passengers:
                    for p in passengers:
                        if pid == str(p.id) or (p.calendar_ids and pid in p.calendar_ids) or str(pid).lower() == getattr(p, 'name', '').lower():
                            resolved_pids_for_this_passenger.add(str(p.id))
                            if p.calendar_ids:
                                for cid in p.calendar_ids:
                                    resolved_pids_for_this_passenger.add(str(cid))
                
                passenger_found = False
                for r_pid in resolved_pids_for_this_passenger:
                    if r_pid in event.calendar_ids:
                        passenger_found = True
                        break
                
                if not passenger_found:
                    match_pax = False
                    break
        else:
            match_pax = False
            resolved_pids = set()
            for pid in raw_pids:
                resolved_pids.add(str(pid))
                if passengers:
                    for p in passengers:
                        if pid == str(p.id) or (p.calendar_ids and pid in p.calendar_ids) or str(pid).lower() == getattr(p, 'name', '').lower():
                            resolved_pids.add(str(p.id))
                            if p.calendar_ids:
                                for cid in p.calendar_ids:
                                    resolved_pids.add(str(cid))
                            
            for pid in resolved_pids:
                if pid in event.calendar_ids:
                    match_pax = True
                    break
                    
        if not match_pax: top_matches = False
        
    # 3. Days of Week
    if top_matches and hasattr(rule, 'days_of_week') and rule.days_of_week:
        has_top_criteria = True
        if event.start.weekday() not in rule.days_of_week: top_matches = False
        
    # 4. Time Window
    if top_matches and hasattr(rule, 'time_start') and rule.time_start:
        has_top_criteria = True
        try:
            h, m = map(int, rule.time_start.split(':'))
            if event.start.hour * 60 + event.start.minute < h * 60 + m: top_matches = False
        except: pass
        
    if top_matches and hasattr(rule, 'time_end') and rule.time_end:
        has_top_criteria = True
        try:
            h, m = map(int, rule.time_end.split(':'))
            if event.end.hour * 60 + event.end.minute > h * 60 + m: top_matches = False
        except: pass

    # 5. Location
    if top_matches and hasattr(rule, 'location') and rule.location:
        has_top_criteria = True
        if not event.location or rule.location.lower() not in event.location.lower():
            top_matches = False

    if has_top_criteria and top_matches:
        return True
        
    if hasattr(rule, 'filter_sets') and rule.filter_sets:
        for fs in rule.filter_sets:
            if does_event_match_rule(event, fs, passengers):
                return True

    return False

def get_grouped_event_pairs(events: List[Event], rules: List[Rule], passengers: List[Passenger]) -> set:
    grouped_event_pairs = set()
    group_rules = [r for r in rules if getattr(r, 'constraint_type', None) == 'group']
    from collections import defaultdict
    for r in group_rules:
        daily_matches = defaultdict(list)
        for e in events:
            if does_event_match_rule(e, r, passengers):
                daily_matches[e.start.date()].append(e)
        for group_events in daily_matches.values():
            if len(group_events) > 1:
                # Group all pairs in this day that matched this rule
                for i in range(len(group_events)):
                    for j in range(i + 1, len(group_events)):
                        grouped_event_pairs.add((group_events[i].id, group_events[j].id))
                        grouped_event_pairs.add((group_events[j].id, group_events[i].id))
    
    # Implicitly group events that are physically the same event
    # (Same base ID, or Same title + start time + location)
    implicit_groups = defaultdict(list)
    for e in events:
        # Group by base ID
        base_id = getattr(e, 'original_event_id', None)
        if not base_id:
            base_id = e.id
            
        if '_unrolled_' in base_id:
            base_id = base_id.split('_unrolled_')[0]
            
        # Differentiate split events so they DO NOT group together (user request)
        if e.id.endswith('_dropoff'):
            base_id = f"{base_id}_dropoff"
        elif e.id.endswith('_pickup'):
            base_id = f"{base_id}_pickup"
            
        implicit_groups[base_id].append(e)
        
        # Group by title, start, and location fallback
        if e.title:
            loc = e.location.strip().lower() if e.location else ""
            normalized_title = e.title.strip().lower()
            key = (normalized_title, e.start, loc)
            implicit_groups[key].append(e)
            
    for group_events in implicit_groups.values():
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
    passengers: List[Passenger] = None,
    trip_metadata: List[dict] = None,
    theme: dict = None
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
    if theme is None:
        theme = {}
        
    unassigned_penalty_mult = theme.get('unassigned_penalty_multiplier', 1.0)
    stickiness_bonus_mult = theme.get('stickiness_bonus_multiplier', 1.0)
    travel_time_penalty_mult = theme.get('travel_time_penalty_multiplier', 1.0)
    primary_driver_bonus_mult = theme.get('primary_driver_bonus_multiplier', 1.0)
    same_loc_bonus_mult = theme.get('same_location_bonus_multiplier', 1.0)
        
    # Resolve effective overrides (instance overrides take precedence over series overrides)
    effective_overrides_list = []
    # Sort descending by created_at to ensure newer overrides take precedence if duplicate
    sorted_overrides = sorted(overrides, key=lambda x: getattr(x, 'created_at', x.get('created_at', 0) if isinstance(x, dict) else 0) or 0, reverse=True)
    
    for e in events:
        instance_o = next((o for o in sorted_overrides if (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.id)), None)
        original_o = next((o for o in sorted_overrides if getattr(e, 'original_event_id', None) and (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.original_event_id)), None)
        series_o = next((o for o in sorted_overrides if getattr(e, 'recurring_event_id', None) and (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.recurring_event_id)), None)
        
        effective_o = instance_o or original_o or series_o
        if effective_o:
            if isinstance(effective_o, dict):
                effective_copy = dict(**effective_o)
                effective_copy['event_id'] = e.id
            else:
                effective_copy = type(effective_o)(**effective_o.model_dump()) if hasattr(effective_o, 'model_dump') else type(effective_o)(**effective_o.dict()) if hasattr(effective_o, 'dict') else type(effective_o)(**effective_o)
                effective_copy.event_id = e.id
            effective_overrides_list.append(effective_copy)
            
    overrides = effective_overrides_list
        
    # Default missing event locations to home_location to prevent 0-minute teleportation
    for e in events:
        if not getattr(e, 'location', None) or str(e.location).strip() == "":
            e.location = home_location

    # Pre-calculate requires_attendance per event
    req_att_cals = set(cal for p in passengers if p.requires_attendance for cal in p.calendar_ids)
    event_requires_attendance = {}
    for e in events:
        is_req = bool(set(e.calendar_ids).intersection(req_att_cals))
        
        desc = getattr(e, 'description', '') or ''
        has_stay_hashtag = '#stay' in (e.title or '').lower() or '#stay' in desc.lower() or '#wait' in (e.title or '').lower() or '#wait' in desc.lower()
        has_stay_rule = False
        if rules:
            has_stay_rule = any(((r.constraint_type == 'attendance' and (r.attendance_action == 'stay' or r.attendance_action is None)) or r.constraint_type == 'no_split') and does_event_match_rule(e, r, passengers) for r in rules)
            
        if has_stay_hashtag or has_stay_rule:
            is_req = True
            
        event_requires_attendance[e.id] = is_req
        
    model = cp_model.CpModel()
    
    # 1. Variables: assign[e.id, d.id]
    assign_vars = {}
    assignable_events = [e for e in events if getattr(e, 'event_type', '') != 'background_trip']
    
    # Pre-calculate e_entities for trip constraints
    e_entities_map = {}
    if trip_metadata:
        for e in assignable_events:
            entities = set()
            for p in passengers:
                p_tags = p.hashtags
                if not p_tags:
                    p_tags = ['#' + ''.join(c.lower() for c in getattr(p, 'name', '') if c.isalnum())]
                e_title = (e.title or "").lower()
                e_desc = (getattr(e, 'description', '') or "").lower()
                if any(p_tags and (t in e_title or t in e_desc) for t in p_tags):
                    entities.add(f"passenger_{p.id}")
            if hasattr(e, 'calendar_ids') and e.calendar_ids:
                for cid in e.calendar_ids:
                    for p in passengers:
                        if cid == str(p.id) or (p.calendar_ids and cid in p.calendar_ids):
                            entities.add(f"passenger_{p.id}")
            e_entities_map[e.id] = entities

    for e in assignable_events:
        for d in drivers:
            assign_vars[(e.id, d.id)] = model.NewBoolVar(f'assign_{e.id}_{d.id}')
            
            # Trip Assignment Constraint
            if trip_metadata:
                e_ents = e_entities_map.get(e.id, set())
                for trip in trip_metadata:
                    trip_ents = trip.get('entities', set())
                    is_global = 'global' in trip_ents
                    
                    if e.start < trip['end'] and e.end > trip['start']:
                        driver_on_trip = (f"driver_{d.id}" in trip_ents) or is_global
                        pax_on_trip = bool(e_ents.intersection(trip_ents)) or is_global
                        
                        if driver_on_trip:
                            # Driver on trip can ONLY take events explicitly linked to this trip
                            if event_trip_id != trip_id:
                                if (e.id, d.id) not in overridden_pairs:
                                    model.Add(assign_vars[(e.id, d.id)] == 0)
                                break
                        else:
                            # Driver NOT on trip CANNOT take events linked to this trip
                            if event_trip_id == trip_id:
                                if (e.id, d.id) not in overridden_pairs:
                                    model.Add(assign_vars[(e.id, d.id)] == 0)
                                break
                            # Driver NOT on trip CANNOT take non-trip events for passengers who are on this trip
                            elif pax_on_trip:
                                if (e.id, d.id) not in overridden_pairs:
                                    model.Add(assign_vars[(e.id, d.id)] == 0)
                                break

    # 2. Constraint: Each event is assigned to AT MOST 1 driver
    for e in assignable_events:
        model.AddAtMostOne(assign_vars[(e.id, d.id)] for d in drivers)

    # 2b. Constraint: A passenger cannot be scheduled for overlapping events at different locations
    for i in range(len(assignable_events)):
        for j in range(i + 1, len(assignable_events)):
            e1 = assignable_events[i]
            e2 = assignable_events[j]
            # True physical overlap in time
            if e1.start < e2.end and e2.start < e1.end:
                # Share passengers
                shared = get_event_passenger_ids(e1, passengers).intersection(get_event_passenger_ids(e2, passengers))
                if shared:
                    # Block overlap if they are at different locations OR if either is missing a location
                    if not (e1.location and e2.location and e1.location.strip().lower() == e2.location.strip().lower()):
                        # However, if BOTH are overridden, we shouldn't add this constraint to prevent INFEASIBLE
                        o1 = any((o.get('event_id') if isinstance(o, dict) else o.event_id) == e1.id for o in effective_overrides_list)
                        o2 = any((o.get('event_id') if isinstance(o, dict) else o.event_id) == e2.id for o in effective_overrides_list)
                        if not (o1 and o2):
                            model.Add(
                                sum(assign_vars[(e1.id, d.id)] for d in drivers) +
                                sum(assign_vars[(e2.id, d.id)] for d in drivers) <= 1
                            )

    # 3. Constraint: No Overlap + Travel Time
    objective_terms = []
    
    e_tolerances = {}
    e_buffer_before = {}
    e_buffer_after = {}
    for e in assignable_events:
        tol_arr = 0
        tol_dep = 0
        bb = 0
        ba = 0
        for r in rules:
            if does_event_match_rule(e, r, passengers):
                if r.constraint_type == 'tolerance':
                    t_mins = getattr(r, 'tolerance_mins', 0)
                    t_type = getattr(r, 'tolerance_type', 'both')
                    if t_type in ['arrival', 'both']:
                        tol_arr = max(tol_arr, t_mins)
                    if t_type in ['departure', 'both']:
                        tol_dep = max(tol_dep, t_mins)
                elif r.constraint_type == 'buffer':
                    bb = max(bb, getattr(r, 'buffer_before_mins', 0))
                    ba = max(ba, getattr(r, 'buffer_after_mins', 0))
        e_tolerances[e.id] = {'arrival': tol_arr, 'departure': tol_dep}
        e_buffer_before[e.id] = bb
        e_buffer_after[e.id] = ba
        
    grouped_event_pairs = get_grouped_event_pairs(assignable_events, rules, passengers)

    # Sort events by start time to easily check pairs
    sorted_events = sorted(assignable_events, key=lambda x: x.start)
    for i in range(len(sorted_events)):
        for j in range(i + 1, len(sorted_events)):
            e1 = sorted_events[i]
            e2 = sorted_events[j]
            
            # Skip conflict checks for events starting more than 3 hours apart
            if (e2.start - e1.end).total_seconds() > 10800:
                break
                
            shares_passenger = bool(get_event_passenger_ids(e1, passengers).intersection(get_event_passenger_ids(e2, passengers)))
            
            if shares_passenger:
                if getattr(e1, 'original_event_id', None) and getattr(e1, 'original_event_id', None) == getattr(e2, 'original_event_id', None):
                    pass
                else:
                    e1_end_time = getattr(e1, 'original_end', None) or e1.end
                    e2_start_time = getattr(e2, 'original_start', None) or e2.start

                    travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                    min_needed_seconds = (travel_time_mins) * 60
                    desired_needed_seconds = min_needed_seconds + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                    gap_seconds = (e2_start_time - e1_end_time).total_seconds()
                    
                    # Check attendance constraints
                    attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                    
                    gap_seconds_with_tolerance = gap_seconds + (e_tolerances.get(e2.id, {}).get('arrival', 0) * 60) + (e_tolerances.get(e1.id, {}).get('departure', 0) * 60)
                    # If they share a passenger, the passenger is attending both events and will simply arrive late.
                    # We do not ban them with a hard penalty here, as it would prevent BOTH events from being scheduled.
                    # BUT we must enforce it if the events overlap heavily (e.g., > 30 minutes), because then it's a true double-booking.
                    is_true_double_booking = (gap_seconds < -1800)
                    if gap_seconds_with_tolerance < min_needed_seconds and not (shares_passenger and not is_true_double_booking):
                        # Passenger conflict hard penalty (impossible)
                        model.Add(sum(assign_vars[(e1.id, d.id)] for d in drivers) + sum(assign_vars[(e2.id, d.id)] for d in drivers) <= 1)
                    elif gap_seconds < desired_needed_seconds:
                        # Passenger conflict soft penalty (buffer eaten into)
                        both = model.NewBoolVar(f'pass_buffer_conf_{e1.id}_{e2.id}')
                        sum_assigned = sum(assign_vars[(e1.id, d.id)] for d in drivers) + sum(assign_vars[(e2.id, d.id)] for d in drivers)
                        model.Add(sum_assigned <= 1 + both)
                        objective_terms.append(both * -50)
                                
            # Driver Conflict Logic
            travel_time_mins = get_switch_travel_time(e1, e2, events, home_location=theme.get('home_location') if theme else None)
            min_needed_seconds = (travel_time_mins) * 60
            desired_needed_seconds = min_needed_seconds + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
            gap_seconds = (e2.start - e1.end).total_seconds()
            
            if (e1.location and e2.location and (e1.location.strip().lower() == e2.location.strip().lower() or get_travel_time_minutes(e1.location, e2.location) <= 5)):
                if travel_time_mins <= 5: # Only bypass if there's no long pickup involved
                    gap_seconds = float('inf')
            attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
            if not attendance_conflict and e1.location and e2.location:
                req_d1_d2 = get_switch_travel_time(e1, e2, events, home_location=theme.get('home_location') if theme else None) * 60
                late_drop_e2 = max(0, req_d1_d2 - (e2.start - e1.start).total_seconds())
                
                # In profile overlap checks, we use min_needed_seconds strictly since it's already tight
                t1 = get_travel_time_minutes(e1.location, e2.location)
                req_e1_e2 = t1 * 60 + (5 * 60 if t1 > 2 else 0)
                t2 = get_travel_time_minutes(e2.location, e1.location)
                req_e2_e1 = t2 * 60 + (5 * 60 if t2 > 2 else 0)
                
                tol_e1 = max(e_tolerances.get(e1.id, {}).values()) * 60 if e1.id in e_tolerances else 0
                tol_e2 = max(e_tolerances.get(e2.id, {}).values()) * 60 if e2.id in e_tolerances else 0
                
                if gap_seconds < 0:
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

            gap_seconds_with_tolerance = gap_seconds + (e_tolerances.get(e2.id, {}).get('arrival', 0) * 60) + (e_tolerances.get(e1.id, {}).get('departure', 0) * 60)
            
            # If they share a passenger, the driver is transporting the passenger between their back-to-back events.
            # Even if the calendar events overlap, they must be allowed to make the drive. We bypass the hard driver conflict penalty.
            is_true_double_booking = (gap_seconds < -1800)
            if gap_seconds_with_tolerance < min_needed_seconds and not (shares_passenger and not is_true_double_booking):
                # Driver conflict hard penalty (impossible)
                for d in drivers:
                    if d.id == 'unassigned_ghost': continue
                    model.AddImplication(assign_vars[(e1.id, d.id)], assign_vars[(e2.id, d.id)].Not())
            elif gap_seconds < min_needed_seconds and not shares_passenger:
                # Driver relies on tolerance! This is a physical overlap saved by tolerance.
                # We heavily penalize this so the solver prefers a clean secondary driver over a primary driver using tolerance.
                for d in drivers:
                    if d.id == 'unassigned_ghost': continue
                    tol = model.NewBoolVar(f'drv_tol_conf_{e1.id}_{e2.id}_{d.id}')
                    model.AddImplication(tol, assign_vars[(e1.id, d.id)])
                    model.AddImplication(tol, assign_vars[(e2.id, d.id)])
                    model.AddBoolOr([tol, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                    
                    # Fixed massive penalty (overcomes Primary Bonus and Group Bonus)
                    penalty = 50000
                    objective_terms.append(tol * -penalty)
            elif gap_seconds < desired_needed_seconds:
                # Driver conflict soft penalty (buffer eaten into)
                for d in drivers:
                    if d.id == 'unassigned_ghost': continue
                    both = model.NewBoolVar(f'drv_buffer_conf_{e1.id}_{e2.id}_{d.id}')
                    model.AddImplication(both, assign_vars[(e1.id, d.id)])
                    model.AddImplication(both, assign_vars[(e2.id, d.id)])
                    model.AddBoolOr([both, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                    # Scaled to overcome Primary Driver Bonus
                    objective_terms.append(both * -2000)

    # 3b. Overridden pairs
    overridden_pairs = set(
        (o.event_id if not isinstance(o, dict) else o.get('event_id'),
         o.driver_id if not isinstance(o, dict) else o.get('driver_id'))
        for o in overrides
    )

    # 3c. Driver Personal Calendar Overlaps
    for d in drivers:
        d_events = driver_events.get(d.id, [])
        for e in assignable_events:
            for de in d_events:
                if getattr(de, 'event_type', '') == 'background_trip':
                    continue
                e_orig = getattr(e, 'original_event_id', None) or e.id
                de_orig = getattr(de, 'original_event_id', None) or de.id
                if e.id == de.id or e_orig == de_orig or e.id == de_orig or e_orig == de.id:
                    continue # Driver is an attendee of this event, do not block
                
                if e.location and de.location:
                    travel = get_travel_time_minutes(e.location, de.location)
                else:
                    travel = 20
                needed_secs_e_to_de = (travel) * 60 + e_buffer_after.get(e.id, 0) * 60
                needed_secs_de_to_e = (travel) * 60 + e_buffer_before.get(e.id, 0) * 60
                
                # Check for overlap, allowing for tolerance
                e_before_de = (de.start - e.end).total_seconds() + (e_tolerances.get(e.id, {}).get('departure', 0) * 60) >= needed_secs_e_to_de
                de_before_e = (e.start - de.end).total_seconds() + (e_tolerances.get(e.id, {}).get('arrival', 0) * 60) >= needed_secs_de_to_e
                
                # True physical overlap in time
                if e.start < de.end and e.end > de.start:
                    if (e.id, d.id) not in overridden_pairs:
                        model.Add(assign_vars[(e.id, d.id)] == 0)
                else:
                    # Transit overlap
                    if not e_before_de and not de_before_e:
                        # Transit impossible. Severely penalize instead of banning so least-bad driver is picked if forced
                        objective_terms.append(assign_vars[(e.id, d.id)] * -2000000)

    # 4. Rules & Objective
    
    for e in assignable_events:
        # Calculate dynamic base weight for the event
        base_event_weight = int(1000000 * unassigned_penalty_mult)
        for pr in priority_rules:
            mod = pr.weight_modifier
            if mod == 500 or mod == 200: mod = 500000
            elif mod == 100: mod = 100000
            elif mod == -100: mod = -100000
            elif mod == -500: mod = -500000
            
            if does_event_match_rule(e, pr, passengers):
                base_event_weight += mod
                
        for d in drivers:
            weight = base_event_weight
            
            # Huge bonus if driver is an attendee of the event
            e_orig_bonus = getattr(e, 'original_event_id', None) or e.id
            is_attendee = False
            for de in driver_events.get(d.id, []):
                de_orig = getattr(de, 'original_event_id', None) or de.id
                if de.id == e.id or de.id == e_orig_bonus or de_orig == e_orig_bonus or de_orig == e.id:
                    is_attendee = True
                    break
                if de.start == e.start and de.end == e.end and de.title.strip().lower() == e.title.strip().lower():
                    is_attendee = True
                    break
                    
            if is_attendee:
                weight += 50000000

            # Group weight
            if d.group == 'primary':
                weight += int(2000 * primary_driver_bonus_mult)
            elif d.group == 'secondary':
                weight += 0
                
            # Priority within group (lower index = higher priority)
            weight += max(0, (10 - d.priority_index) * 150)
            
            # Preferred hours penalty
            if d.preferred_start or d.preferred_end:
                try:
                    e_start_time = e.start.time()
                    e_end_time = e.end.time()
                    
                    p_start = datetime.strptime(d.preferred_start, '%H:%M').time() if d.preferred_start else None
                    p_end = datetime.strptime(d.preferred_end, '%H:%M').time() if d.preferred_end else None
                    
                    if (p_start and e_start_time < p_start) or (p_end and e_end_time > p_end):
                        weight -= 2000000
                except ValueError:
                    pass
            
            # Stickiness
            if previous_assignments.get(e.id) == d.id:
                weight += int(5 * stickiness_bonus_mult)
                
            # Apply Driver Rules
            avoid_penalty = 0
            for r in rules:
                r_type = getattr(r, 'constraint_type', '')
                a_type = getattr(r, 'assignment_type', '')
                if r_type in ['required', 'preferred', 'unavailable', 'avoid']:
                    a_type = r_type
                    r_type = 'assignment'

                # Simple keyword matching (case-insensitive)
                if does_event_match_rule(e, r, passengers) and r.driver_id == d.id:
                    if r_type == 'assignment':
                        if a_type == 'required':
                            # This driver MUST do it, meaning all other drivers cannot
                            for other_d in drivers:
                                if other_d.id != d.id:
                                    if (e.id, other_d.id) not in overridden_pairs:
                                        model.Add(assign_vars[(e.id, other_d.id)] == 0)
                            weight += 500
                        elif a_type == 'preferred':
                            weight += 10000
                        elif a_type == 'unavailable':
                            if (e.id, d.id) not in overridden_pairs:
                                model.Add(assign_vars[(e.id, d.id)] == 0)
                        elif a_type == 'avoid':
                            avoid_penalty = 100000
                            
            if avoid_penalty > 0:
                weight = min(weight - avoid_penalty, 1)

            objective_terms.append(assign_vars[(e.id, d.id)] * weight)
            
    # 4b. Passenger and Location Continuity Bonus
    for i in range(len(sorted_events)):
        for j in range(i + 1, len(sorted_events)):
            e1 = sorted_events[i]
            e2 = sorted_events[j]
            shares_passenger = bool(get_event_passenger_ids(e1, passengers).intersection(get_event_passenger_ids(e2, passengers)))
            same_loc = bool(e1.location and e2.location and e1.location.strip().lower() == e2.location.strip().lower())
            
            if e1.start.date() == e2.start.date():
                if shares_passenger or same_loc:
                    for d in drivers:
                        both_assigned = model.NewBoolVar(f'both_{e1.id}_{e2.id}_{d.id}')
                        model.AddImplication(both_assigned, assign_vars[(e1.id, d.id)])
                        model.AddImplication(both_assigned, assign_vars[(e2.id, d.id)])
                        model.AddBoolOr([both_assigned, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                        
                        if shares_passenger:
                            if same_loc:
                                travel_mins = 0
                            elif (e2.start - e1.end).total_seconds() > 3600:
                                travel_mins = 99  # Skip Maps API query for events far apart
                            else:
                                travel_mins = get_travel_time_minutes(e1.location, e2.location)
                        else:
                            if (e2.start - e1.end).total_seconds() > 3600:
                                travel_mins = 99
                            else:
                                travel_mins = get_switch_travel_time(e1, e2, events, home_location=theme.get('home_location') if theme else None, trip_metadata=trip_metadata, passengers=passengers)
                        
                        gap_seconds = (e2.start - e1.end).total_seconds()
                        if gap_seconds >= 0:
                            if shares_passenger:
                                # Estimate if a layover home trip would occur. If it does, we zero out the continuity bonus.
                                # For estimating, we use the global home_location as a proxy for the driver's home.
                                global_home = theme.get('home_location') if theme else None
                                active_driver_home = get_active_home(f"driver_{d.id}", e2.start.timestamp(), global_home, trip_metadata) if trip_metadata and global_home else global_home
                                threshold_seconds = 7200 # default to 2 hours if we can't estimate
                                if active_driver_home and e1.location and e2.location:
                                    t_home = get_travel_time_minutes(e1.location, active_driver_home)
                                    t_back = get_travel_time_minutes(active_driver_home, e2.location)
                                    # Drive home kicks in if layover >= 20 mins. Layover = gap_mins - t_home - t_back - 5.
                                    # gap_mins = 20 + 5 + t_home + t_back = 25 + t_home + t_back
                                    threshold_seconds = (25 + t_home + t_back) * 60
                                    
                                # Linearly decay passenger stickiness bonus from 50,000 (at 0 gap) down to 0 (at threshold_seconds gap).
                                # This aligns perfectly with the threshold where a driver typically has enough time to go home for a layover.
                                decay = max(0.0, 1.0 - (gap_seconds / max(1.0, threshold_seconds)))
                                if decay > 0:
                                    objective_terms.append(both_assigned * int(50000 * decay * stickiness_bonus_mult))
                                    
                            if gap_seconds < 10800: # 3 hours
                                if (travel_mins == 0 and e1.location and e2.location) or ((travel_mins <= 5) and shares_passenger):
                                    # Higher bonus for doing things at the exact same location (reduces travel)
                                    decay_loc = max(0.0, 1.0 - (gap_seconds / 10800.0))
                                    objective_terms.append(both_assigned * int(5000 * decay_loc * same_loc_bonus_mult))
                                    
                                # Penalize travel time only if the gap is small enough that the driver wouldn't go home
                                # If the gap is > 1 hour (3600s), travel_mins is set to 99 to skip API. In this case, there is no direct travel penalty because they went home.
                                if gap_seconds <= 3600:
                                    objective_terms.append(both_assigned * (-int(travel_mins * 60 * travel_time_penalty_mult)))
                    
    # 4c. Mutually Exclusive Event Groups

    mut_ex_rules = [r for r in rules if r.constraint_type == 'duplicate' and getattr(r, 'duplicate_action', '') == 'schedule_one']
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
                    
        # Add a massive bonus for assigning both grouped events to the SAME driver.
        # This incentivizes the solver to pick an event that is part of a group over an ungrouped duplicate.
        for d in drivers:
            both_assigned = model.NewBoolVar(f'group_bonus_{e1_id}_{e2_id}_{d.id}')
            model.AddImplication(both_assigned, assign_vars[(e1_id, d.id)])
            model.AddImplication(both_assigned, assign_vars[(e2_id, d.id)])
            model.AddBoolOr([both_assigned, assign_vars[(e1_id, d.id)].Not(), assign_vars[(e2_id, d.id)].Not()])
            objective_terms.append(both_assigned * 1000)
    # 4e. Override weights
    import time
    base_time = time.time()
    for o in overrides:
        o_event_id = o.get('event_id') if isinstance(o, dict) else o.event_id
        o_driver_id = o.get('driver_id') if isinstance(o, dict) else o.driver_id
        if any(e.id == o_event_id for e in assignable_events):
            if o_driver_id == 'unassigned':
                for d in drivers:
                    if d.id != 'unassigned_ghost':
                        model.Add(assign_vars[(o_event_id, d.id)] == 0)
            elif any(d.id == o_driver_id for d in drivers):
                # Calculate weight: Base 1,000,000 + seconds since override was created
                # This ensures newer overrides always win over older ones if they conflict
                try:
                    # If created_at is not present (old overrides), default to 0
                    created_at = getattr(o, 'created_at', o.get('created_at', 0) if isinstance(o, dict) else 0)
                    time_weight = int(float(created_at)) if created_at else 0
                except:
                    time_weight = 0
                objective_terms.append(assign_vars[(o_event_id, o_driver_id)] * (100000000 + time_weight))
            
    # Maximize total score
    model.Maximize(sum(objective_terms))
    
    # 5. Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
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
                
                # Skip lateness checks for events starting more than 3 hours apart
                if (e2.start - e1.end).total_seconds() > 10800:
                    break
                    
                d1_id = assignments.get(e1.id)
                d2_id = assignments.get(e2.id)
                
                if d1_id and d2_id:
                    shares_passenger = bool(get_event_passenger_ids(e1, passengers).intersection(get_event_passenger_ids(e2, passengers)))
                    if shares_passenger:
                        travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                        total_needed_seconds = (travel_time_mins) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                        gap_seconds = (e2.start - e1.end).total_seconds()
                        if gap_seconds < total_needed_seconds:
                            mins_late = int((total_needed_seconds - gap_seconds) / 60)
                            # We attach the warning to e2 since it's the one they are arriving late to
                            lateness_warnings[e2.id] = f"Passenger will be {mins_late}m late (arriving from {e1.title})"
                    elif d1_id == d2_id:
                        travel_time_mins = get_switch_travel_time(e1, e2, events)
                        total_needed_seconds = (travel_time_mins) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
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
        
    mut_ex_rules = [r for r in rules if r.constraint_type == 'duplicate' and getattr(r, 'duplicate_action', '') == 'schedule_one']
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
            shares_passenger = bool(get_event_passenger_ids(e, passengers).intersection(get_event_passenger_ids(ae, passengers)))
            if shares_passenger:
                travel_time_mins = get_travel_time_minutes(e.location, ae.location)
                
                if e.start <= ae.start:
                    first, second = e, ae
                else:
                    first, second = ae, e
                total_needed_seconds = (travel_time_mins) * 60 + e_buffer_after.get(first.id, 0) * 60 + e_buffer_before.get(second.id, 0) * 60    
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
            
            # Skip conflict checks for events starting more than 3 hours apart
            if (e2.start - e1.end).total_seconds() > 10800:
                break
                
            shares_passenger = bool(get_event_passenger_ids(e1, passengers).intersection(get_event_passenger_ids(e2, passengers)))
            
            if shares_passenger:
                travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                total_needed_seconds = (travel_time_mins) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                if (e2.start - e1.end).total_seconds() < total_needed_seconds:
                    # Passenger conflict
                    is_assigned_e1 = sum(assign_vars[(e1.id, g_id)] for g_id in ghost_ids)
                    is_assigned_e2 = sum(assign_vars[(e2.id, g_id)] for g_id in ghost_ids)
                    model.Add(is_assigned_e1 + is_assigned_e2 <= 1)
            else:
                travel_time_mins = get_switch_travel_time(e1, e2, events)
                total_needed_seconds = (travel_time_mins) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                if (e2.start - e1.end).total_seconds() < total_needed_seconds:
                    # Driver conflict
                    for g_id in ghost_ids:
                        model.AddImplication(assign_vars[(e1.id, g_id)], assign_vars[(e2.id, g_id)].Not())
                    
    used_vars = {}
    for g_id in ghost_ids:
        used_vars[g_id] = model.NewBoolVar(f'used_{g_id}')
        for e in events:
            model.AddImplication(assign_vars[(e.id, g_id)], used_vars[g_id])
            
    # Symmetry breaking: force lower-indexed ghost drivers to be used before higher-indexed ones
    for i in range(len(ghost_ids) - 1):
        model.AddImplication(used_vars[ghost_ids[i+1]], used_vars[ghost_ids[i]])
            
    objective_terms = []
    for i, g_id in enumerate(ghost_ids):
        objective_terms.append(used_vars[g_id] * (1000 + i))
        
    model.Minimize(sum(objective_terms))
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
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
        
        # If the passenger has a large gap (> 45 mins) and the next event is not at the same location,
        # we can safely assume they were dropped off at home rather than waiting for hours.
        gap_minutes = (e2.start.timestamp() - e_b_prev.end.timestamp()) / 60
        same_loc = bool(e_b_prev.location and e2.location and e_b_prev.location.strip().lower() == e2.location.strip().lower())
        
        if gap_minutes > 45 and not same_loc:
            return None
            
        return e_b_prev
    return None

def get_passenger_pickup_event(e2: Event, all_events: List[Event]) -> Optional[Event]:
    return get_passenger_pickup_event_for_subset(e2, set(e2.calendar_ids), all_events)

def get_switch_travel_time(e1: Event, e2: Event, all_events: List[Event], home_location: Optional[str] = None, trip_metadata: List[dict] = None, passengers: List[Passenger] = None) -> int:
    pickup = get_passenger_pickup_event(e2, all_events)
    if pickup:
        t1 = get_travel_time_minutes(e1.location, pickup.location)
        t2 = get_travel_time_minutes(pickup.location, e2.location)
        return t1 + t2
    
    if home_location and e1.location and e2.location:
        if passengers and trip_metadata:
            e2_pax_ids = get_event_passenger_ids(e2, passengers)
            if e2_pax_ids:
                p_id = list(e2_pax_ids)[0]
                active_home = get_active_home(f"passenger_{p_id}", e2.start.timestamp(), home_location, trip_metadata)
                
                # If no pickup event is found, it means the passenger is at home.
                # The driver must travel from e1 to home, then home to e2.
                t1 = get_travel_time_minutes(e1.location, active_home)
                t2 = get_travel_time_minutes(active_home, e2.location)
                return t1 + t2
    
    # Fallback if no home location or no passenger involved
    
    # Fallback if no home location
    same_loc = bool(e1.location and e2.location and e1.location.strip().lower() == e2.location.strip().lower())
    if same_loc:
        return 0
    return get_travel_time_minutes(e1.location, e2.location)

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
    
    def get_active_home_local(entity_id: str, ts: float, default_home: str) -> str:
        return get_active_home(entity_id, ts, default_home, trip_metadata)

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
            date_evs = [e for e in date_evs_iter if getattr(e, 'event_type', '') != 'background_trip']
            if not date_evs:
                continue
                
            if driver_default_home and driver_default_home.strip() != "":
                first_ev = date_evs[0]
                is_passenger_ev = first_ev.id in assignments
                
                start_ts = first_ev.start.timestamp()
                driver_home = get_active_home_local(f'driver_{d_id}', start_ts, driver_default_home)
                global_home_at_start = get_active_home_local('global', start_ts, home_location)
                
                pax_home = global_home_at_start
                pickup_title = "Home"
                if is_passenger_ev:
                    assigned_events = [ev for ev in events if ev.id in assignments]
                    pickup_event = get_passenger_pickup_event_for_subset(first_ev, set(first_ev.calendar_ids), assigned_events)
                    if pickup_event:
                        pax_home = pickup_event.location
                        pickup_title = pickup_event.title
                    else:
                        for cid in first_ev.calendar_ids:
                            pid = get_pax_id(cid)
                            if pid:
                                pax_home = get_active_home_local(f'passenger_{pid}', start_ts, global_home_at_start)
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
                            "pickup_event_title": pickup_title,
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
                
                last_ev = max(date_evs, key=lambda x: x.end.timestamp())
                is_last_passenger_ev = last_ev.id in assignments
                
                end_ts = last_ev.end.timestamp()
                driver_home_at_end = get_active_home_local(f'driver_{d_id}', end_ts, driver_default_home)
                global_home_at_end = get_active_home_local('global', end_ts, home_location)
                
                pax_home = global_home_at_end
                if is_last_passenger_ev:
                    for cid in last_ev.calendar_ids:
                        pid = get_pax_id(cid)
                        if pid:
                            pax_home = get_active_home_local(f'passenger_{pid}', end_ts, global_home_at_end)
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
                            "travel_mins": travel_to_home,
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
                e1_pax = get_event_passenger_ids(e1, passengers)
                e2_pax = get_event_passenger_ids(e2, passengers)
                shares_passenger = bool(e1_pax.intersection(e2_pax))
                new_passengers = e2_pax - e1_pax
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
                    
                    pickup_waypoint = None
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
                            global_home_at_dep = get_active_home_local('global', dep_time, home_location)
                            pax_home = global_home_at_dep
                            if new_passengers:
                                for cid in new_passengers:
                                    pid = get_pax_id(cid)
                                    if pid:
                                        pax_home = get_active_home_local(f'passenger_{pid}', dep_time, global_home_at_dep)
                                        break
                                
                            driver_home_at_dep = get_active_home_local(f'driver_{d_id}', dep_time, driver_default_home)
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
                    
                driver_home_at_layover = get_active_home_local(f'driver_{d_id}', dep_time, driver_default_home)
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
            needed_secs = (travel) * 60
            
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
    effective_override_map = {}
    
    # Resolve effective overrides for diagnostics
    sorted_overrides = sorted(overrides, key=lambda x: getattr(x, 'created_at', x.get('created_at', 0) if isinstance(x, dict) else 0) or 0, reverse=True)
    for e in events:
        instance_o = next((o for o in sorted_overrides if (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.id)), None)
        original_o = next((o for o in sorted_overrides if getattr(e, 'original_event_id', None) and (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.original_event_id)), None)
        series_o = next((o for o in sorted_overrides if getattr(e, 'recurring_event_id', None) and (getattr(o, 'event_id', o.get('event_id') if isinstance(o, dict) else None) == e.recurring_event_id)), None)
        
        effective_o = instance_o or original_o or series_o
        if effective_o:
            did = getattr(effective_o, 'driver_id', effective_o.get('driver_id') if isinstance(effective_o, dict) else None)
            if did:
                overridden_pairs.add((e.id, did))
                effective_override_map[e.id] = did
    
    for u_id in unassigned_ids:
        e = event_map.get(u_id)
        if not e: continue
        
        diagnostics[u_id] = {}
        for d in drivers:
            reason = None
            
            # 1. Overrides
            eff_did = effective_override_map.get(e.id)
            if eff_did:
                if eff_did != d.id and eff_did != 'unassigned':
                    reason = {"text": "Blocked by Manual Override for another driver.", "type": "override"}
                if eff_did == 'unassigned':
                    reason = {"text": "Blocked by 'Unassigned' override.", "type": "override"}
                
            # 2. Driver Personal Calendar
            if not reason:
                for de in driver_events.get(d.id, []):
                    if e.id == de.id: continue
                    travel = get_travel_time_minutes(e.location, de.location) if e.location and de.location else 20
                    needed_secs = (travel) * 60
                    e_before_de = (de.start - e.end).total_seconds() >= needed_secs
                    de_before_e = (e.start - de.end).total_seconds() >= needed_secs
                    if not e_before_de and not de_before_e:
                        if (e.id, d.id) not in overridden_pairs:
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
                    needs_driver = getattr(ae, 'event_type', '') != 'background_trip'
                    if needs_driver and ae.id not in assignments: continue
                    if e_cals.intersection(ae.calendar_ids):
                        travel = get_travel_time_minutes(e.location, ae.location) if e.location and ae.location else 20
                        needed_secs = (travel) * 60
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
                                "lateness_mins": lateness_mins if lateness_mins > 0 else None,
                                "suggested_tolerance_type": "departure" if e.start <= ae.start else "arrival"
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
                        needed_secs = (travel) * 60
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
                                "lateness_mins": lateness_mins if lateness_mins > 0 else None,
                                "suggested_tolerance_type": "departure" if e.start <= ae.start else "arrival"
                            }
                            break
                        
            # 3. Rule constraints
            if not reason:
                for r in rules:
                    r_type = getattr(r, 'constraint_type', '')
                    a_type = getattr(r, 'assignment_type', '')
                    if r_type in ['required', 'preferred', 'unavailable', 'avoid']:
                        a_type = r_type
                        r_type = 'assignment'

                    if does_event_match_rule(e, r, passengers):
                        if r_type == 'assignment':
                            if a_type == 'unavailable' and r.driver_id == d.id:
                                if (e.id, d.id) not in overridden_pairs:
                                    reason = {"text": "Prohibited by 'Unavailable' rule.", "type": "rule"}
                                    break
                            elif a_type == 'required' and r.driver_id != d.id:
                                if (e.id, d.id) not in overridden_pairs:
                                    reason = {"text": "Blocked by 'Required' rule for another driver.", "type": "rule"}
                                    break
            
            # 4. Overlap with existing assignments
            if not reason:
                for a_id, a_d_id in assignments.items():
                    if a_d_id == d.id and a_id != e.id:
                        a_e = event_map.get(a_id)
                        if a_e:
                            shares_passenger = bool(get_event_passenger_ids(e, passengers).intersection(get_event_passenger_ids(a_e, passengers)))
                            if shares_passenger:
                                travel = get_travel_time_minutes(e.location, a_e.location) if e.location and a_e.location else 20
                            else:
                                travel = get_switch_travel_time(e, a_e, events)
                            needed_secs = (travel) * 60
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
            


def insert_errands_globally(base_schedules: Dict[str, dict], errands: List[dict], drivers: List[dict], trip_metadata: List[dict] = None) -> Dict[str, List[dict]]:
    from datetime import datetime, timedelta, time
    from services import storage
    from models.schemas import Rule
    
    all_rules = storage.get_all_rules()
    
    def requires_stay(e):
        if not hasattr(e, 'title'): return False
        for r_data in all_rules:
            if r_data.get('constraint_type') == 'attendance' and r_data.get('attendance_action') == 'stay':
                try:
                    r_obj = Rule(**r_data)
                except Exception:
                    continue
                if does_event_match_rule(e, r_obj):
                    return True
        return False
        
    def is_valid_time_window(start_t, end_t, tw_start, tw_end):
        if tw_start:
            h, m = map(int, tw_start.split(':'))
            if start_t.time() < time(h, m): return False
        if tw_end:
            h, m = map(int, tw_end.split(':'))
            if end_t.time() > time(h, m): return False
        return True
        
    def get_pax_in_car_at_gap(sched, gap_idx):
        in_car = set()
        for i in range(gap_idx + 1):
            e = sched[i]
            title = e.title.lower() if hasattr(e, 'title') else ''
            is_pickup = title.startswith('pickup')
            is_dropoff = title.startswith('dropoff')
            pids = []
            if hasattr(e, 'passengers') and e.passengers:
                pids = [str(p.id) for p in e.passengers]
            elif hasattr(e, 'passenger_ids') and e.passenger_ids:
                pids = [str(pid) for pid in e.passenger_ids]
                
            if is_pickup:
                in_car.update(pids)
            elif is_dropoff:
                for pid in pids: in_car.discard(pid)
        return in_car

    scheduled_errands_by_date = {date_str: [] for date_str in base_schedules.keys()}
    
    active_errands = [e for e in errands if not e.get('is_completed')]
    if not active_errands:
        return scheduled_errands_by_date
        
    driver_map = {d.id: d for d in drivers if d.id != 'unassigned_ghost'}
    
    # Build driver schedules for each day
    driver_schedules_by_date = {}
    for date_str, daily_data in base_schedules.items():
        assignments = daily_data.get('assignments', {})
        events = daily_data.get('events', [])
        
        day_schedules = {d.id: [] for d in drivers if d.id != 'unassigned_ghost'}
        for e in events:
            d_id = assignments.get(e.id)
            if d_id and d_id in day_schedules:
                day_schedules[d_id].append(e)
                
        for d_id in day_schedules:
            day_schedules[d_id].sort(key=lambda x: x.start)
            
        driver_schedules_by_date[date_str] = day_schedules

    active_errands.sort(key=lambda x: (x.get('priority', 2), -x.get('duration_mins', 30)))
    
    class VirtualEvent:
        def __init__(self, start, end, location):
            self.start = start
            self.end = end
            self.location = location

    for errand in active_errands:
        # Calculate target window
        anchor_ts = errand.get('starts_on') or errand.get('created_at', 0)
        try:
            anchor_date = datetime.fromtimestamp(anchor_ts)
        except:
            anchor_date = datetime.now().astimezone()
            
        rule = errand.get('recurrence_rule')
        
        if rule == 'weekly':
            target_date = anchor_date + timedelta(days=7)
            window_start = (target_date - timedelta(days=2)).date()
            window_end = (target_date + timedelta(days=2)).date()
        elif rule == 'daily':
            target_date = anchor_date + timedelta(days=1)
            window_start = target_date.date()
            window_end = target_date.date()
        elif rule == 'monthly':
            target_date = anchor_date + timedelta(days=30)
            window_start = (target_date - timedelta(days=5)).date()
            window_end = (target_date + timedelta(days=5)).date()
        else: # One-off
            target_date = anchor_date
            window_start = target_date.date()
            if errand.get('window_days'):
                window_end = window_start + timedelta(days=errand.get('window_days') - 1)
            else:
                window_end = datetime.max.date()
            
        # If today is past the window end, it's overdue, so it becomes ASAP
        today_date = datetime.now().date()
        if today_date > window_end:
            window_start = today_date
            window_end = datetime.max.date()
            
        # Check cache to see if already scheduled within the window
        already_scheduled = False
        window_days = (window_end - window_start).days
        max_scan = min(window_days, 60) # cap scan to prevent infinite loop for one-offs
        
        for offset in range(max_scan + 1):
            check_date = window_start + timedelta(days=offset)
            d_str = str(check_date)
            # If we are solving this day currently, it will be handled by the loop below
            if d_str in driver_schedules_by_date:
                continue
                
            cache = storage.get_cached_daily_schedule(d_str)
            if cache and 'schedule' in cache:
                cached_errands = cache['schedule'].get('scheduled_errands', [])
                if any(er.get('id') == errand.get('id') for er in cached_errands):
                    already_scheduled = True
                    break
                    
        if already_scheduled:
            continue
            
        best_gap = None
        best_detour = float('inf')
        duration = errand.get('duration_mins', 30) - errand.get('tolerance_mins', 0)
        duration = max(5, duration) + errand.get('buffer_mins', 0)
        loc = errand.get('location', '')
        
        tw_start = errand.get('time_window_start')
        tw_end = errand.get('time_window_end')
        
        allowed_drivers = errand.get('allowed_drivers', [])
        required_drivers = errand.get('required_drivers', [])
        prohibited_drivers = errand.get('prohibited_drivers', [])
        
        req_pax = set(str(p) for p in errand.get('required_passengers', []))
        proh_pax = set(str(p) for p in errand.get('prohibited_passengers', []))
        
        group_id = errand.get('group_id')
        
        # --- Apply global rules to this errand ---
        from models.schemas import Event, Rule
        try:
            errand_dt = datetime.fromtimestamp(errand.get('starts_on') or errand.get('created_at', 0)).astimezone()
        except:
            errand_dt = datetime.now().astimezone()
            
        dummy_event = Event(
            id=errand.get('id', 'temp'),
            title=errand.get('title', ''),
            start=errand_dt,
            end=errand_dt + timedelta(minutes=duration),
            location=loc,
            calendar_ids=[],
            source_event_ids=[],
            event_type="errand"
        )
        
        for r_data in all_rules:
            try:
                r = Rule(**r_data)
            except Exception:
                continue
            if does_event_match_rule(dummy_event, r):
                r_type = getattr(r, 'constraint_type', '')
                a_type = getattr(r, 'assignment_type', '')
                if r_type in ['required', 'preferred', 'unavailable', 'avoid']:
                    a_type = r_type
                    r_type = 'assignment'
                    
                if r_type == 'assignment':
                    if a_type == 'required' or a_type == 'preferred':
                        if r.driver_id not in required_drivers:
                            required_drivers.append(r.driver_id)
                    elif a_type == 'unavailable' or a_type == 'avoid':
                        if r.driver_id not in prohibited_drivers:
                            prohibited_drivers.append(r.driver_id)
                elif r_type == 'group':
                    if not group_id:
                        group_id = r.id
            if getattr(r, 'window_days', None) and r.window_days < window_days:
                window_days = r.window_days
        # -----------------------------------------
        
        from datetime import timezone
        now = datetime.now().astimezone()
        
        # Sort dates chronologically so we try to schedule the errand on the earliest valid date first
        sorted_dates = sorted(driver_schedules_by_date.keys())
        
        for date_str in sorted_dates:
            day_schedules = driver_schedules_by_date[date_str]
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            
            # Check if this date is within the acceptable window
            if current_date < window_start or current_date > window_end:
                continue
                
            for d_id, schedule in day_schedules.items():
                driver = driver_map.get(d_id)
                if not driver: continue
                
                group_bonus = 0
                if group_id:
                    for e_sched in scheduled_errands_by_date[date_str]:
                        if e_sched.get('group_id') == group_id and e_sched.get('driver', {}).get('id') == d_id:
                            group_bonus = 9999
                            break
                
                if required_drivers and d_id not in required_drivers: continue
                if prohibited_drivers and d_id in prohibited_drivers: continue
                if allowed_drivers and not required_drivers and d_id not in allowed_drivers: continue
                
                default_driver_home = getattr(driver, 'home_location', None)
                if not default_driver_home and hasattr(driver, 'get'):
                    default_driver_home = driver.get('home_location')
                
                from datetime import time
                start_time_ts = datetime.combine(current_date, time(9, 0)).astimezone().timestamp()
                driver_home = get_active_home(f'driver_{d_id}', start_time_ts, default_driver_home, trip_metadata) if trip_metadata else default_driver_home
                
                # If driver is on a trip (home changed) and this errand is NOT tied to this trip (via group_bonus), skip this driver
                if driver_home != default_driver_home and group_bonus == 0:
                    continue
                
                if not schedule:
                    t1 = get_travel_time_minutes(driver_home, loc) if driver_home else 0
                    detour = t1 * 2 - group_bonus
                    start_time = datetime.combine(current_date, time(9, 0)).astimezone() # default 9 AM
                    end_time = start_time + timedelta(minutes=duration)
                    
                    if (not req_pax) and is_valid_time_window(start_time, end_time, tw_start, tw_end) and start_time >= now:
                        if detour < best_detour:
                            best_detour = detour
                            best_gap = (date_str, d_id, start_time, -1)
                    continue
                    
                # Before first event
                first_event = schedule[0]
                t_home_to_loc = get_travel_time_minutes(driver_home, loc) if driver_home else 0
                t_loc_to_first = get_travel_time_minutes(loc, first_event.location)
                t_home_to_first = get_travel_time_minutes(driver_home, first_event.location) if driver_home else 0
                
                detour = t_home_to_loc + t_loc_to_first - t_home_to_first - group_bonus
                start_time = first_event.start - timedelta(minutes=t_loc_to_first + duration)
                end_time = start_time + timedelta(minutes=duration)
                
                if start_time.hour >= 9:
                    if (not req_pax) and is_valid_time_window(start_time, end_time, tw_start, tw_end) and start_time >= now:
                        if detour < best_detour:
                            best_detour = detour
                            best_gap = (date_str, d_id, start_time, -1)
                    
                # Intra-event gaps (Drop-off & Run)
                for i in range(len(schedule)):
                    e = schedule[i]
                    if not requires_stay(e):
                        available_mins = (e.end - e.start).total_seconds() / 60.0
                        t_event_to_errand = get_travel_time_minutes(e.location, loc)
                        t_errand_to_event = get_travel_time_minutes(loc, e.location)
                        total_needed = t_event_to_errand + duration + t_errand_to_event
                        if total_needed <= available_mins:
                            start_time = e.start + timedelta(minutes=t_event_to_errand)
                            end_time = start_time + timedelta(minutes=duration)
                            
                            # Passengers are NOT in the car during an event (they are at the event)
                            if (not req_pax) and is_valid_time_window(start_time, end_time, tw_start, tw_end) and start_time >= now:
                                detour = t_event_to_errand + t_errand_to_event - group_bonus
                                if detour < best_detour:
                                    best_detour = detour
                                    best_gap = (date_str, d_id, start_time, float(f"{i}.5"))

                for i in range(len(schedule) - 1):
                    e1 = schedule[i]
                    e2 = schedule[i+1]
                    gap_mins = (e2.start - e1.end).total_seconds() / 60.0
                    
                    t1 = get_travel_time_minutes(e1.location, loc)
                    t2 = get_travel_time_minutes(loc, e2.location)
                    
                    total_needed = t1 + duration + t2
                    if gap_mins >= total_needed:
                        detour = t1 + t2 - get_travel_time_minutes(e1.location, e2.location) - group_bonus
                        start_time = e1.end + timedelta(minutes=t1)
                        end_time = start_time + timedelta(minutes=duration)
                        
                        in_car = get_pax_in_car_at_gap(schedule, i)
                        pax_valid = True
                        if req_pax and not req_pax.issubset(in_car): pax_valid = False
                        if proh_pax and not proh_pax.isdisjoint(in_car): pax_valid = False
                        
                        if pax_valid and is_valid_time_window(start_time, end_time, tw_start, tw_end) and start_time >= now:
                            if detour < best_detour:
                                best_detour = detour
                                best_gap = (date_str, d_id, start_time, i)
                            
                # After last event
                last_event = schedule[-1]
                t_last_to_loc = get_travel_time_minutes(last_event.location, loc)
                t_loc_to_home = get_travel_time_minutes(loc, driver_home) if driver_home else 0
                t_last_to_home = get_travel_time_minutes(last_event.location, driver_home) if driver_home else 0
                
                detour = t_last_to_loc + t_loc_to_home - t_last_to_home - group_bonus
                start_time = last_event.end + timedelta(minutes=t_last_to_loc)
                end_time = start_time + timedelta(minutes=duration)
                
                if (not req_pax) and is_valid_time_window(start_time, end_time, tw_start, tw_end) and start_time >= now:
                    if detour < best_detour:
                        best_detour = detour
                        best_gap = (date_str, d_id, start_time, len(schedule)-1)
                    
        if best_gap:
            date_str, d_id, start_time, idx = best_gap
            end_time = start_time + timedelta(minutes=duration)
            
            schedule = day_schedules[d_id]
            e1_id = None
            e2_id = None
            t1 = 0
            t2 = 0
            
            if len(schedule) > 0:
                if idx == -1:
                    e2 = schedule[0]
                    e2_id = getattr(e2, 'id', None)
                    t1 = get_travel_time_minutes(driver_home, loc) if driver_home else 0
                    t2 = get_travel_time_minutes(loc, e2.location)
                elif idx == len(schedule) - 1:
                    e1 = schedule[-1]
                    e1_id = getattr(e1, 'id', None)
                    t1 = get_travel_time_minutes(e1.location, loc)
                    t2 = get_travel_time_minutes(loc, driver_home) if driver_home else 0
                else:
                    if isinstance(idx, float):
                        real_idx = int(idx)
                        e1 = schedule[real_idx]
                        e1_id = getattr(e1, 'id', None)
                        e2_id = e1_id
                        t1 = get_travel_time_minutes(e1.location, loc)
                        t2 = get_travel_time_minutes(loc, e1.location)
                        idx = real_idx
                    else:
                        e1 = schedule[idx]
                        e2 = schedule[idx + 1]
                        e1_id = getattr(e1, 'id', None)
                        e2_id = getattr(e2, 'id', None)
                        t1 = get_travel_time_minutes(e1.location, loc)
                        t2 = get_travel_time_minutes(loc, e2.location)
            
            ve = VirtualEvent(start_time, end_time, loc)
            driver_schedules_by_date[date_str][d_id].insert(idx + 1, ve)
            
            scheduled_errands_by_date[date_str].append({
                "id": errand.get('id'),
                "doc_id": errand.get('doc_id'),
                "group_id": errand.get('group_id'),
                "driver": driver_map[d_id].model_dump() if hasattr(driver_map[d_id], 'model_dump') else driver_map[d_id].dict(),
                "event_type": "errand",
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "title": errand.get('title'),
                "location": loc,
                "priority": errand.get('priority'),
                "inserted_after_event_id": e1_id,
                "inserted_before_event_id": e2_id,
                "travel_to_mins": t1,
                "travel_from_mins": t2
            })
            
    return scheduled_errands_by_date
