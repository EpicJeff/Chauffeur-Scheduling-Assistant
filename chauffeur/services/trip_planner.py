import uuid
import datetime
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple

from models.schemas import TripMetadata, TripPOI, Event
from services import storage, maps, calendar

def generate_trip_pois(trip: TripMetadata, user_prompt: str, duration_days: int = 1) -> List[TripPOI]:
    """
    Generates a list of suggested Trip POIs based on the user's prompt using the LLM,
    and grounds them to real-world locations via Mapbox.
    """
    from services.llm import _call_llm_json
    
    settings = storage.get_settings()
    provider = settings.get('llm_provider', 'gemini')
    if provider == 'ollama':
        url = settings.get('llm_ollama_url', 'http://localhost:11434')
        model = settings.get('llm_ollama_model', 'qwen2.5:7b')
        api_key = None
    else:
        url = ""
        model = settings.get('llm_gemini_model', 'gemini-3.5-flash')
        api_key = settings.get('llm_gemini_api_key')
        
    system_prompt = """You are an expert travel agent. 
The user will provide a prompt describing what they want to do on their trip.
The user's trip is """ + str(duration_days) + """ days long. Your job is to suggest enough Points of Interest (POIs) to fill this trip (aim for 2-3 POIs per day, up to a maximum of 12 suggestions per response) that match their request and are located in or near the specified Trip Location.
If the user already has POIs on their itinerary, try to suggest new places that complement them (e.g. suggesting a nice restaurant near a planned museum, or an evening activity that fits the vibe).

You MUST respond with a single valid JSON object of the following exact structure:
{
  "suggestions": [
    {
      "name": "The name of the location (e.g., French Laundry)",
      "category": "A predefined category string. MUST be one of exactly these: 'sightseeing', 'food', 'activity', 'shopping', or 'other'",
      "description": "A 1-2 sentence compelling description of the experience.",
      "why_picked": "Explain why this specifically matches the user's request (e.g., 'You mentioned wanting a Michelin star experience...').",
      "experience": "Describe what they will actually do there, what the vibe is like, or tips for the visit.",
      "search_query": "The best search query to find this exact place on a map (e.g. 'French Laundry, Yountville, CA')",
      "duration_mins": 90,
      "ideal_time_start": "09:00",
      "ideal_time_end": "12:00"
    }
  ]
}
Note: `ideal_time_start` and `ideal_time_end` MUST be 24-hour HH:MM strings. If flexible, use "09:00" and "21:00". `duration_mins` should be an integer in minutes based on how long a visit usually takes.
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON.
"""
    
    existing_poi_names = [p.name for p in trip.pois] if trip.pois else []
    existing_pois_str = ", ".join(existing_poi_names) if existing_poi_names else "None"
    
    user_req = (
        f"Trip Title: {trip.title or 'Unknown'}\n"
        f"Trip Location: {trip.location or 'Unknown'}\n"
        f"Trip Notes/Context: {trip.notes or 'None'}\n"
        f"Existing POIs (DO NOT suggest these again): {existing_pois_str}\n"
        f"User Request: {user_prompt}\n"
        f"Generate suggestions."
    )
    
    try:
        response_json = _call_llm_json(provider, url, api_key, model, system_prompt, user_req, temperature=0.7)
    except Exception as e:
        print(f"Error generating POIs: {e}")
        return []
        
    suggestions = response_json.get('suggestions', [])
    pois = []
    
    for s in suggestions:
        name = s.get('name')
        query = s.get('search_query', name)
        
        # Ground to real location using Mapbox autocomplete/search
        locations = maps.autocomplete_location(query)
        best_location = query # Fallback
        mapbox_id = None
        
        if locations:
            # Pick the first result
            best_location = locations[0].get('description', query)
            mapbox_id = locations[0].get('mapbox_id')
            
        encoded_query = urllib.parse.quote(f"{name} {best_location}")
        image_url = f"/api/unsplash/background?query={urllib.parse.quote(name)}"
        link = f"https://www.google.com/maps/search/?api=1&query={encoded_query}"
            
        poi = TripPOI(
            id=uuid.uuid4().hex,
            name=name,
            location=best_location,
            mapbox_id=mapbox_id,
            category=s.get('category'),
            description=s.get('description'),
            why_picked=s.get('why_picked'),
            experience=s.get('experience'),
            image_url=image_url,
            link=link,
            ideal_time_start=s.get('ideal_time_start'),
            ideal_time_end=s.get('ideal_time_end'),
            duration_mins=s.get('duration_mins', 90)
        )
        pois.append(poi)
        
    return pois

def schedule_poi(trip: TripMetadata, poi: TripPOI) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    """
    Finds the best open time slot during the trip and schedules the POI in Google Calendar (or isolated environment if draft).
    Returns a tuple of (event_id, error_reason, suggested_fixes). If successful, error_reason is None.
    """
    settings = storage.get_settings()
    cals = settings.get('calendar_ids', [])
    if not cals:
        return None, "No calendars configured in settings.", None
        
    if trip.is_draft:
        # Isolated Scheduling Engine
        if not trip.mock_start_date or not trip.mock_end_date:
            return None, "Draft trip has no dates set.", None
        trip_start = datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc)
        trip_end = datetime.datetime.fromtimestamp(trip.mock_end_date, tz=datetime.timezone.utc)
        trip_cals = cals
        
        # Build overlapping events from already scheduled POIs
        overlapping_events = []
        for p in trip.pois:
            if p.is_scheduled and p.id != poi.id and p.scheduled_start and p.scheduled_end:
                class MockEvent:
                    def __init__(self, start, end, location):
                        self.start = start
                        self.end = end
                        self.location = location
                overlapping_events.append(MockEvent(
                    datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc),
                    datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc),
                    p.location
                ))
    else:
        # Standard Scheduling Engine
        events = calendar.fetch_upcoming_events(cals, days=60)
        trip_event = next((e for e in events if e.id == trip.event_id or trip.event_id in e.source_event_ids), None)
        
        if not trip_event:
            print("Trip event not found, cannot schedule POI.")
            return None, "The main trip event could not be found on your calendar.", None
            
        trip_start = trip_event.start
        trip_end = trip_event.end
        
        trip_cals = trip_event.calendar_ids
        if not trip_cals:
            trip_cals = cals
            
        overlapping_events = []
        for e in events:
            if e.id == trip_event.id:
                continue
            if e.end > trip_start and e.start < trip_end:
                if any(c in trip_cals for c in e.calendar_ids):
                    overlapping_events.append(e)
                
    overlapping_events.sort(key=lambda x: x.start)
    
    current_time = trip_start
    best_start = None
    
    import zoneinfo
    trip_tz_str = getattr(trip, 'timeZone', None)
    if not trip_tz_str or trip_tz_str == "UTC":
        if trip.location:
            from services.maps import get_timezone
            new_tz = get_timezone(trip.location)
            if new_tz and new_tz != "UTC":
                trip_tz_str = new_tz
    try:
        local_tz = zoneinfo.ZoneInfo(trip_tz_str or "UTC")
    except Exception:
        local_tz = datetime.timezone.utc
    
    ideal_start_time = None
    ideal_end_time = None
    if poi.ideal_time_start:
        try: ideal_start_time = datetime.datetime.strptime(poi.ideal_time_start, "%H:%M").time()
        except: pass
    if poi.ideal_time_end:
        try: ideal_end_time = datetime.datetime.strptime(poi.ideal_time_end, "%H:%M").time()
        except: pass
        
    if not ideal_start_time: ideal_start_time = datetime.time(9, 0)
    if not ideal_end_time: ideal_end_time = datetime.time(21, 0)
    
    # Hard cap: don't start anything after 9:30 PM unless it's explicitly marked for nightlife
    hard_cap_start = datetime.time(21, 30)
    
    duration_delta = datetime.timedelta(minutes=poi.duration_mins)
    buffer_delta = datetime.timedelta(minutes=30)
    
    is_food = poi.category == 'food'
    is_dessert = False
    if is_food:
        poi_text = f"{poi.name or ''} {poi.description or ''}".lower()
        if any(w in poi_text for w in ['dessert', 'ice cream', 'gelato', 'sweet', 'cafe', 'coffee', 'bakery', 'pastry']):
            is_dessert = True

    scheduled_pois_by_date = {}
    for p in trip.pois:
        if p.is_scheduled and p.id != poi.id and p.scheduled_start:
            p_dt = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc).astimezone(local_tz)
            date_str = p_dt.strftime("%Y-%m-%d")
            if date_str not in scheduled_pois_by_date:
                scheduled_pois_by_date[date_str] = []
            scheduled_pois_by_date[date_str].append(p)
            
    valid_slots = []
    location_travel_times = {}
    
    def find_slots(enforce_ideal_times=True):
        slots = []
        curr = trip_start
        while curr + duration_delta <= trip_end:
            slot_start = curr
            slot_end = curr + duration_delta
            curr += datetime.timedelta(minutes=30)
            
            slot_local = slot_start.astimezone(local_tz)
            slot_time = slot_local.time()
            slot_date = slot_local.strftime("%Y-%m-%d")
            
            if slot_time > hard_cap_start and not (poi.ideal_time_end and "23" in poi.ideal_time_end):
                continue
                
            if enforce_ideal_times:
                if slot_time < ideal_start_time or slot_end.astimezone(local_tz).time() > ideal_end_time:
                    continue
                
            overlaps = False
            for e in overlapping_events:
                # Use dynamic travel time instead of static buffer
                travel_mins = 30
                if getattr(e, 'location', None) and getattr(poi, 'location', None):
                    poi_loc_clean = poi.location.lower().strip()
                    e_loc_clean = e.location.lower().strip()
                    if poi_loc_clean == e_loc_clean:
                        travel_mins = 0
                    else:
                        key = (e.location, poi.location)
                        if key not in location_travel_times:
                            location_travel_times[key] = maps.get_travel_time_minutes(e.location, poi.location)
                        travel_mins = location_travel_times[key]
                
                dynamic_buffer = datetime.timedelta(minutes=travel_mins)
                
                # The slot cannot overlap with the event + the dynamic travel buffer
                if (slot_start - dynamic_buffer) < e.end and (slot_end + dynamic_buffer) > e.start:
                    overlaps = True
                    break
                    
            if overlaps:
                continue
                
            is_lunch_block = datetime.time(11, 0) <= slot_time < datetime.time(14, 0)
            is_dinner_block = datetime.time(17, 0) <= slot_time < datetime.time(21, 0)
            
            if is_food and not is_dessert:
                conflict = False
                scheduled_on_day = scheduled_pois_by_date.get(slot_date, [])
                non_dessert_food = []
                for sp in scheduled_on_day:
                    if sp.category == 'food':
                        sp_text = f"{sp.name or ''} {sp.description or ''}".lower()
                        sp_is_dessert = any(w in sp_text for w in ['dessert', 'ice cream', 'gelato', 'sweet', 'cafe', 'coffee', 'bakery', 'pastry'])
                        if not sp_is_dessert:
                            non_dessert_food.append(sp)
                            
                if len(non_dessert_food) >= 2:
                    conflict = True
                elif len(non_dessert_food) == 1:
                    sp = non_dessert_food[0]
                    sp_time = datetime.datetime.fromtimestamp(sp.scheduled_start, tz=datetime.timezone.utc).astimezone(local_tz).time()
                    is_sp_lunch = sp_time < datetime.time(16, 0)
                    is_slot_lunch = slot_time < datetime.time(16, 0)
                    if is_sp_lunch == is_slot_lunch:
                        conflict = True
                
                if conflict:
                    continue
                    
            score = 0
            days_from_start = (slot_local.date() - trip_start.astimezone(local_tz).date()).days
            score += max(0, 100 - (days_from_start * 10))
            
            scheduled_on_day = scheduled_pois_by_date.get(slot_date, [])
            for sp in scheduled_on_day:
                poi_loc_clean = (poi.location or "").lower().strip()
                sp_loc_clean = (sp.location or "").lower().strip()
                poi_name_lower = (poi.name or "").lower()
                sp_name_lower = (sp.name or "").lower()
                
                if poi.location and sp.location and (poi_loc_clean == sp_loc_clean or poi_name_lower in sp_name_lower or sp_name_lower in poi_name_lower):
                    score += 1000
                    
                if poi.location and sp.location:
                    key = (sp.location, poi.location)
                    if key not in location_travel_times:
                        location_travel_times[key] = maps.get_travel_time_minutes(sp.location, poi.location)
                    travel_mins = location_travel_times[key]
                    if travel_mins <= 15:
                        score += 500
                    elif travel_mins <= 30:
                        score += 250
                        
                    sp_start = datetime.datetime.fromtimestamp(sp.scheduled_start, tz=datetime.timezone.utc).astimezone(local_tz)
                    sp_end = datetime.datetime.fromtimestamp(sp.scheduled_end, tz=datetime.timezone.utc).astimezone(local_tz)
                    # If very close, and scheduled right after, right before, or overlapping, give a clustering bonus!
                    if travel_mins <= 15 and (
                        (sp_end <= slot_start <= sp_end + datetime.timedelta(hours=2)) or
                        (sp_start - datetime.timedelta(hours=2) <= slot_end <= sp_start) or
                        (slot_start >= sp_start and slot_end <= sp_end) or
                        (slot_start <= sp_start and slot_end >= sp_end)
                    ):
                        score += 1500
                        
                if is_dessert and sp.category == 'food':
                    sp_end = datetime.datetime.fromtimestamp(sp.scheduled_end, tz=datetime.timezone.utc)
                    if sp_end <= slot_start <= sp_end + datetime.timedelta(hours=2):
                        score += 2000
                        
            slots.append((score, slot_start))
        return slots
        
    valid_slots = find_slots(enforce_ideal_times=True)
        
    if not valid_slots:
        suggested_fixes = []
        if ideal_start_time != datetime.time(9, 0) or ideal_end_time != datetime.time(21, 0):
            # Try without ideal times
            alt_slots = find_slots(enforce_ideal_times=False)
            if alt_slots:
                alt_slots.sort(key=lambda x: (-x[0], x[1]))
                best_alt_start = alt_slots[0][1]
                suggested_fixes.append({
                    "type": "clear_times",
                    "label": f"Schedule at {best_alt_start.strftime('%a %I:%M %p')} (Ignore Ideal Times)"
                })
        
        return None, "Could not find an available time slot matching constraints (e.g. ideal times, overlapping activities, or meal conflicts).", {"suggested_fixes": suggested_fixes}
        
    valid_slots.sort(key=lambda x: (-x[0], x[1]))
    best_start = valid_slots[0][1]
        
    best_end = best_start + datetime.timedelta(minutes=poi.duration_mins)
    
    if trip.is_draft:
        # Save mock timestamps, bypass Google Calendar
        event_id = f"draft_poi_{uuid.uuid4().hex}"
        poi.is_scheduled = True
        poi.scheduled_start = best_start.timestamp()
        poi.scheduled_end = best_end.timestamp()
        poi.event_id = event_id
        return event_id, None, None
    
    target_cal = trip_cals[0] if trip_cals else cals[0]
    
    desc = poi.description or ""
    if poi.notes:
        desc += f"\n\nNotes: {poi.notes}"
        
    event_id = calendar.create_event(
        calendar_id=target_cal,
        title=f"Trip: {poi.name}",
        start=best_start.isoformat(),
        end=best_end.isoformat(),
        location=poi.location,
        description=desc,
        trip_id=trip.id,
        poi_id=poi.id
    )
    
    if event_id:
        poi.is_scheduled = True
        poi.scheduled_start = best_start.timestamp()
        poi.scheduled_end = best_end.timestamp()
        poi.event_id = event_id
        return event_id, None, None
        
    return None, "Failed to create the event in Google Calendar.", None

def schedule_pois_bulk(trip: TripMetadata, poi_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Schedules multiple POIs at once using a clustering algorithm based on distance and priority.
    Returns a dictionary mapping poi_id to a dict containing {"success": bool, "reason": str}.
    """
    settings = storage.get_settings()
    cals = settings.get('calendar_ids', [])
    results = {}
    
    if not cals:
        for pid in poi_ids:
            results[pid] = {"success": False, "reason": "No calendars configured in settings."}
        return results
        
    target_pois = [p for p in trip.pois if p.id in poi_ids and not p.is_scheduled]
    if not target_pois:
        return results
        
    # Pre-cache distances
    locations = [p.location for p in target_pois if p.location]
    maps.prime_matrix_cache(locations)
    
    # Priority grouping
    prio_map = {'must': 3, 'want': 2, 'stretch': 1}
    target_pois.sort(key=lambda x: prio_map.get(x.priority or 'want', 2), reverse=True)
    
    # Simple Greedy Clustering
    clusters = [] # list of lists of POIs
    for p in target_pois:
        added = False
        for cluster in clusters:
            # Check travel time to cluster centroid (just use the first item)
            centroid = cluster[0]
            if not p.location or not centroid.location:
                continue
            travel_mins = maps.get_travel_time_minutes(centroid.location, p.location)
            if travel_mins <= 20:
                cluster.append(p)
                added = True
                break
        if not added:
            clusters.append([p])
            
    # Schedule each cluster as a block
    for cluster in clusters:
        for poi in cluster:
            # For now, just reuse the single scheduler but we can upgrade this to block scheduling
            # since the single scheduler now correctly handles dynamic buffers!
            event_id, reason, meta = schedule_poi(trip, poi)
            if event_id:
                results[poi.id] = {"success": True, "reason": None}
            else:
                results[poi.id] = {"success": False, "reason": reason}
                if meta and "suggested_fixes" in meta:
                    results[poi.id]["suggested_fixes"] = meta["suggested_fixes"]
                
    return results
