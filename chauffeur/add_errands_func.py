import re

filepath = r'e:\repositories\Chauffeur\chauffeur\solver\matcher.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

func_code = """
def insert_errands_into_schedule(assignments: Dict[str, str], daily_events: List[Event], errands: List[dict], drivers: List[dict]) -> List[dict]:
    from datetime import datetime, timedelta
    
    active_errands = [e for e in errands if not e.get('is_completed')]
    if not active_errands:
        return []
        
    driver_map = {d['id']: d for d in drivers if d['id'] != 'unassigned_ghost'}
    
    driver_schedules = {d['id']: [] for d in drivers if d['id'] != 'unassigned_ghost'}
    for e in daily_events:
        d_id = assignments.get(e.id)
        if d_id and d_id in driver_schedules:
            driver_schedules[d_id].append(e)
            
    for d_id in driver_schedules:
        driver_schedules[d_id].sort(key=lambda x: x.start)
        
    scheduled_errands = []
    
    active_errands.sort(key=lambda x: (x.get('priority', 2), -x.get('duration_mins', 30)))
    
    for errand in active_errands:
        best_gap = None
        best_detour = float('inf')
        duration = errand.get('duration_mins', 30)
        loc = errand.get('location', '')
        
        for d_id, schedule in driver_schedules.items():
            driver = driver_map.get(d_id)
            if not driver: continue
            
            if not schedule:
                continue
                
            for i in range(len(schedule) - 1):
                e1 = schedule[i]
                e2 = schedule[i+1]
                gap_mins = (e2.start - e1.end).total_seconds() / 60.0
                
                t1 = get_travel_time_minutes(e1.location, loc)
                t2 = get_travel_time_minutes(loc, e2.location)
                
                total_needed = t1 + duration + t2
                if gap_mins >= total_needed:
                    detour = t1 + t2 - get_travel_time_minutes(e1.location, e2.location)
                    if detour < best_detour:
                        best_detour = detour
                        best_gap = (d_id, e1.end + timedelta(minutes=t1), i)
                        
            last_event = schedule[-1]
            t1 = get_travel_time_minutes(last_event.location, loc)
            detour = t1
            if detour < best_detour:
                best_detour = detour
                best_gap = (d_id, last_event.end + timedelta(minutes=t1), len(schedule)-1)
                
        if best_gap:
            d_id, start_time, idx = best_gap
            end_time = start_time + timedelta(minutes=duration)
            
            class VirtualEvent:
                def __init__(self, start, end, location):
                    self.start = start
                    self.end = end
                    self.location = location
            ve = VirtualEvent(start_time, end_time, loc)
            driver_schedules[d_id].insert(idx + 1, ve)
            
            scheduled_errands.append({
                "id": errand.get('id'),
                "doc_id": errand.get('doc_id'),
                "driver": driver_map[d_id],
                "event_type": "errand",
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "title": errand.get('title'),
                "location": loc,
                "priority": errand.get('priority')
            })
            
    return scheduled_errands
"""

if "def insert_errands_into_schedule" not in content:
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write("\n" + func_code)
