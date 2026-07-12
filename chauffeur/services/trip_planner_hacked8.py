import uuid
import datetime
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple

from models.schemas import TripMetadata, TripPOI, Event, TripAccommodation
from services import storage, maps, calendar

def enrich_poi_data(name: str, location_query: str, trip_location: str) -> dict:
    """
    Takes a basic POI name and location query and enriches it with Mapbox/Wikidata details.
    Returns a dictionary of extra metadata to append to the POI.
    """
    import re
    clean_query = re.sub(r'\(.*?\)', '', location_query).strip()
    clean_name = re.sub(r'\(.*?\)', '', name).strip()
    
    locations = maps.search_places(clean_query, trip_location)
    best_location = location_query # Fallback
    mapbox_id = None
    poi_lat = None
    poi_lng = None
    wikidata_id = None
    opening_hours = None
    website = None
    phone_number = None
    cuisine = None
    internet_access = None
    
    if locations:
        best_location = locations[0].get('address') or locations[0].get('name') or location_query
        mapbox_id = locations[0].get('mapbox_id')
        poi_lat = locations[0].get('lat')
        poi_lng = locations[0].get('lon')
        wikidata_id = locations[0].get('wikidata_id')
        opening_hours = locations[0].get('opening_hours')
        website = locations[0].get('website')
        phone_number = locations[0].get('phone_number')
        cuisine = locations[0].get('cuisine')
        internet_access = locations[0].get('internet_access')
        
    encoded_query = urllib.parse.quote(f"{name} {best_location}")
    
    if wikidata_id:
        image_url = f"api/unsplash/background?query={urllib.parse.quote(clean_name)}&wikidata_id={wikidata_id}"
    else:
        image_url = f"api/unsplash/background?query={urllib.parse.quote(clean_name)}"
        
    link = f"https://www.google.com/maps/search/?api=1&query={encoded_query}"
    
    return {
        "location": best_location,
        "mapbox_id": mapbox_id,
        "lat": poi_lat,
        "lng": poi_lng,
        "wikidata_id": wikidata_id,
        "opening_hours": opening_hours,
        "website": website,
        "phone_number": phone_number,
        "cuisine": cuisine,
        "internet_access": internet_access,
        "image_url": image_url,
        "link": link
    }

def generate_trip_pois(trip: TripMetadata, user_prompt: str, duration_days: int = 1, proposed_itinerary: str = "") -> Tuple[Optional[str], List[TripPOI]]:
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
        
    num_pois = max(1, duration_days * 4)
    system_prompt = f"""You are an expert travel agent. 
The user will provide a prompt describing what they want to do on their trip.
The user's trip is {duration_days} days long. 
If the user asks for a specific number of places or specific items, you MUST generate exactly what they asked for and nothing more.
If their request is open-ended, suggest approximately {num_pois} Points of Interest (POIs) to fill this trip that match their request and are located in or near the specified Trip Location.
If the user already has POIs on their itinerary, try to suggest new places that complement them (e.g. suggesting a nice restaurant near a planned museum, or an evening activity that fits the vibe).
CRITICAL: Do NOT include accommodations (like hotels, resorts, or Airbnbs) in your suggestions. This is strictly for attractions, activities, and dining.

You MUST respond with a single valid JSON object of the following exact structure:
{{
  "budget_warning": "Optional string. If you cannot meet the user's budget with these suggestions, populate this warning explaining why and asking where they are willing to compromise. Still generate your best-effort suggestions.",
  "suggestions": [
    {{
      "name": "The name of the location (e.g., French Laundry)",
      "category": "A predefined category string. MUST be one of exactly these: 'sightseeing', 'food', 'activity', 'shopping', or 'other'",
      "description": "A 1-2 sentence compelling description of the experience.",
      "why_picked": "Explain why this specifically matches the user's request (e.g., 'You mentioned wanting a Michelin star experience...').",
      "experience": "Describe what they will actually do there, what the vibe is like, or tips for the visit.",
      "search_query": "The best search query to find this exact place on a map (e.g. 'French Laundry, Yountville, CA')",
      "duration_mins": 90,
      "ideal_time_start": "09:00",
      "ideal_time_end": "12:00",
      "estimated_price_usd": 20.0,
      "is_background": false,
      "valid_days_of_week": [],
      "occurrences": 1
    }}
  ]
}}
`is_background` should be true ONLY if this POI is an umbrella event/location (like a theme park or resort) that spans an entire day or multiple days, and other POIs will be scheduled concurrently inside of it. CRITICAL: For ANY major Theme Park or National Park (e.g. Magic Kingdom, EPCOT, Universal Studios), you MUST set `is_background` to true! Default False. `valid_days_of_week` is an optional array of integers (0=Mon, 6=Sun) representing the ONLY days this POI can be scheduled. CRITICAL: Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6. You MUST map the day name in the proposed itinerary to the exact integer, ignoring relative "Day 1" labels. If the user's prompt mentions preferred days, crowd optimization, or avoiding crowds for specific places, you MUST populate this field with the corresponding day integers (e.g., [1, 2, 4]) to force the solver to schedule it exactly on those days. `occurrences` should be an integer > 1 ONLY if the user explicitly mentions they want to do this activity MULTIPLE times or for MULTIPLE days (e.g., "3 days at Disney" = occurrences: 3). If they say "3 days", you MUST set occurrences to 3. Otherwise default to 1.
CRITICAL: If the category is 'food', you MUST populate `ideal_time_start` and `ideal_time_end` with the typical meal window (e.g., '12:00' and '13:30' for lunch, or '18:00' and '20:00' for dinner) to prevent it from being scheduled at inappropriate times like 7:00 AM.
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON.
"""
    
    existing_poi_names = [p.name for p in trip.pois] if trip.pois else []
    existing_pois_str = ", ".join(existing_poi_names) if existing_poi_names else "None"
    
    import datetime
    if trip.is_draft and trip.mock_start_date:
        trip_start_dt = datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc)
        trip_end_dt = trip_start_dt + datetime.timedelta(days=duration_days)
    else:
        from services.calendar import get_event_dates
        trip_start_dt, trip_end_dt = get_event_dates(trip.event_id)
        if not trip_start_dt or not trip_end_dt:
            trip_start_dt = datetime.datetime.now(datetime.timezone.utc)
            trip_end_dt = trip_start_dt + datetime.timedelta(days=duration_days)
            
    if trip.is_draft:
        date_bounds_str = f"Trip Duration: {duration_days} days\nNOTE: This is a draft trip being plotted on a mock future calendar year to avoid overlapping with current events.\nThe assigned mock start date is {trip_start_dt.strftime('%Y-%m-%d')} ({trip_start_dt.strftime('%A')}) and the end date is {trip_end_dt.strftime('%Y-%m-%d')} ({trip_end_dt.strftime('%A')}).\nIMPORTANT: Estimate all prices using TODAY'S current prices."
    else:
        date_bounds_str = f"Trip Start Date: {trip_start_dt.strftime('%Y-%m-%d')} ({trip_start_dt.strftime('%A')})\nTrip End Date: {trip_end_dt.strftime('%Y-%m-%d')} ({trip_end_dt.strftime('%A')})"
        
    budget_context = ""
    if getattr(trip, 'budget_max_usd', None) is not None:
        budget_min = getattr(trip, 'budget_min_usd', 0) or 0
        budget_context = f"The user has a target trip budget between ${budget_min} and ${trip.budget_max_usd}. Keep this in mind when estimating prices.\n"
        budget_context += "CRITICAL BUDGET INSTRUCTION: If the total estimated cost of your suggestions exceeds the user's maximum budget, you MUST populate the 'budget_warning' field explaining why and asking where they are willing to compromise. You must STILL provide the best-effort suggestions in the arrays.\n"
        
    travelers = getattr(trip, 'travelers', 1)
    budget_context += f"This trip is for {travelers} traveler(s). Your estimated_price_usd MUST reflect the total cost for the ENTIRE group (not per person).\n"

    proposed_str = ""
    if proposed_itinerary:
        proposed_str = f"CRITICAL INSTRUCTION: The assistant has already promised the user the following itinerary. You MUST align the POIs, their `valid_days_of_week`, and `ideal_time_start`/`ideal_time_end` exactly with this itinerary so the final schedule matches what the user expects.\nProposed Itinerary: {proposed_itinerary}\n"
        
    user_req = (
        f"Trip Title: {trip.title or 'Unknown'}\n"
        f"Trip Location: {trip.location or 'Unknown'}\n"
        f"{date_bounds_str}\n"
        f"Trip Notes/Context: {trip.notes or 'None'}\n"
        f"{budget_context}"
        f"Existing POIs (DO NOT suggest these again): {existing_pois_str}\n"
        f"{proposed_str}"
        f"User Request: {user_prompt}\n"
        f"Generate suggestions."
    )
    
    try:
        response_json = _call_llm_json(provider, url, api_key, model, system_prompt, user_req, temperature=0.7)
    except Exception as e:
        print(f"Error generating POIs: {e}")
        return None, []
        
    budget_warning = response_json.get('budget_warning')
    suggestions = response_json.get('suggestions', [])
    
    # Keyword check: If a POI is obviously a hotel but the LLM placed it here, we should drop it.
    acc_keywords = ['hotel', 'resort', 'motel', 'inn', 'airbnb', 'hyatt', 'marriott', 'hilton', 'lodge', 'suites', 'villa', 'bnb']
    true_suggestions = []
    for s in suggestions:
        name_lower = s.get('name', '').lower()
        if any(k in name_lower.split() or name_lower.startswith(f"{k} ") or name_lower.endswith(f" {k}") for k in acc_keywords):
            continue
        true_suggestions.append(s)
    suggestions = true_suggestions

    pois = []
    
    for s in suggestions:
        name = s.get('name')
        query = s.get('search_query', name)
        
        enrichment = enrich_poi_data(name, query, trip.location)
        
        occurrences = s.get('occurrences', 1)
        for i in range(occurrences):
            name_label = s.get('name') if occurrences == 1 else f"{s.get('name')} (Day {i+1})"
            poi = TripPOI(
                id=uuid.uuid4().hex,
                name=name_label,
                location=enrichment['location'],
                mapbox_id=enrichment['mapbox_id'],
                category=s.get('category', 'other'),
                description=s.get('description'),
                why_picked=s.get('why_picked'),
                experience=s.get('experience'),
                image_url=enrichment['image_url'],
                link=enrichment['link'],
                ideal_time_start=s.get('ideal_time_start'),
                ideal_time_end=s.get('ideal_time_end'),
                duration_mins=s.get('duration_mins', 90),
                valid_days_of_week=s.get('valid_days_of_week', []),
                occurrences=1,
                is_background=s.get('is_background', False),
                lat=enrichment['lat'],
                lng=enrichment['lng'],
                wikidata_id=enrichment['wikidata_id'],
                opening_hours=enrichment['opening_hours'],
                website=enrichment['website'],
                phone_number=enrichment['phone_number'],
                cuisine=enrichment['cuisine'],
                internet_access=enrichment['internet_access'],
                estimated_price_usd=s.get('estimated_price_usd')
            )
            pois.append(poi)
        
    if getattr(trip, 'budget_max_usd', None):
        total = sum((p.estimated_price_usd or 0) for p in pois)
        if total > trip.budget_max_usd and not budget_warning:
            budget_warning = f"Warning: The total estimated cost of these attractions (${total:,.2f}) exceeds your maximum budget of ${trip.budget_max_usd:,.2f}. Please review and let me know where you'd like to compromise."
            
    return budget_warning, pois

def schedule_poi(trip: TripMetadata, poi: TripPOI, bounds: Optional[Tuple[datetime.datetime, datetime.datetime]] = None) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    """
    Finds the best open time slot during the trip and schedules the POI in Google Calendar (or isolated environment if draft).
    Returns a tuple of (event_id, error_reason, suggested_fixes). If successful, error_reason is None.
    """
    settings = storage.get_settings()
    cals = settings.get('calendar_ids', [])
    if not cals:
        return None, "No calendars configured in settings.", None
        
    import zoneinfo
    trip_tz_str = getattr(trip, 'timeZone', None)
    if not trip_tz_str or trip_tz_str == "UTC":
        if trip.location:
            from services.maps import get_timezone
            tz_str = get_timezone(trip.location)
            local_tz = zoneinfo.ZoneInfo(tz_str) if tz_str and tz_str != "UTC" else zoneinfo.ZoneInfo('America/New_York')
        else:
            local_tz = zoneinfo.ZoneInfo('America/New_York')
    else:
        try:
            local_tz = zoneinfo.ZoneInfo(trip_tz_str)
        except Exception:
            local_tz = zoneinfo.ZoneInfo('America/New_York')
        
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
                p_is_bg = getattr(p, 'is_background', False)
                if getattr(poi, 'is_background', False):
                    if not p_is_bg: continue
                else:
                    if p_is_bg: continue
                
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
                
        accommodation_events = []
        for acc in getattr(trip, 'accommodations', []):
            if acc.check_in_date and acc.check_out_date:
                class MockAccEvent:
                    def __init__(self, start, end, location):
                        self.start = start
                        self.end = end
                        self.location = location
                try:
                    start_dt = datetime.datetime.strptime(acc.check_in_date, "%Y-%m-%d").replace(hour=15, tzinfo=local_tz)
                    end_dt = datetime.datetime.strptime(acc.check_out_date, "%Y-%m-%d").replace(hour=11, tzinfo=local_tz)
                    accommodation_events.append(MockAccEvent(start_dt, end_dt, acc.location))
                except Exception:
                    pass
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
        accommodation_events = []
        for e in events:
            if e.id == trip_event.id:
                continue
            is_e_bg = (getattr(e, 'event_type', 'standard') == 'trip_background')
            
            if is_e_bg:
                if getattr(e, 'trip_id', None) == trip.id:
                    if not getattr(e, 'poi_id', None):
                        accommodation_events.append(e)
            
            if getattr(poi, 'is_background', False):
                if not is_e_bg: continue
            else:
                if is_e_bg: continue
                
            if e.end > trip_start and e.start < trip_end:
                if any(c in trip_cals for c in e.calendar_ids):
                    overlapping_events.append(e)
                    
        for p in trip.pois:
            if p.is_scheduled and p.id != poi.id and p.scheduled_start and p.scheduled_end:
                p_is_bg = getattr(p, 'is_background', False)
                if getattr(poi, 'is_background', False):
                    if not p_is_bg: continue
                else:
                    if p_is_bg: continue
                
                if getattr(p, 'event_id', '') and p.event_id.startswith("draft_poi_"):
                    class MockEvent:
                        def __init__(self, start, end, location):
                            self.start = start
                            self.end = end
                            self.location = location
                            
                    start_dt = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
                    end_dt = datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)
                        
                    overlapping_events.append(MockEvent(
                        start_dt,
                        end_dt,
                        p.location
                    ))
                    
        for acc in getattr(trip, 'accommodations', []):
            if acc.check_in_date and acc.check_out_date:
                # If it's already on the calendar, we caught it in events loop.
                # If it's not on the calendar yet (no event_id or draft), add it manually.
                if not getattr(acc, 'event_id', None) or str(acc.event_id).startswith("draft_"):
                    class MockAccEvent:
                        def __init__(self, start, end, location):
                            self.start = start
                            self.end = end
                            self.location = location
                    try:
                        start_dt = datetime.datetime.strptime(acc.check_in_date, "%Y-%m-%d").replace(hour=15, tzinfo=local_tz)
                        end_dt = datetime.datetime.strptime(acc.check_out_date, "%Y-%m-%d").replace(hour=11, tzinfo=local_tz)
                        accommodation_events.append(MockAccEvent(start_dt, end_dt, acc.location))
                    except Exception:
                        pass
                
    if bounds:
        bound_start, bound_end = bounds
        trip_start = max(trip_start, bound_start)
        trip_end = min(trip_end, bound_end)

    overlapping_events.sort(key=lambda x: x.start)
    
    current_time = trip_start
    best_start = None
    
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
    
    poi_hours_start = None
    poi_hours_end = None
    if getattr(poi, 'opening_hours', None):
        oh = poi.opening_hours.lower()
        if '24/7' in oh:
            poi_hours_start = datetime.time(0, 0)
            poi_hours_end = datetime.time(23, 59)
        else:
            import re
            match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?\s*-\s*(\d{1,2}):(\d{2})\s*(am|pm)?', oh)
            if match:
                try:
                    h1, m1, ap1, h2, m2, ap2 = match.groups()
                    h1, m1, h2, m2 = int(h1), int(m1), int(h2), int(m2)
                    if ap1 == 'pm' and h1 < 12: h1 += 12
                    if ap1 == 'am' and h1 == 12: h1 = 0
                    if ap2 == 'pm' and h2 < 12: h2 += 12
                    if ap2 == 'am' and h2 == 12: h2 = 0
                    poi_hours_start = datetime.time(h1, m1)
                    poi_hours_end = datetime.time(h2, m2)
                except ValueError:
                    pass
    

    duration_delta = datetime.timedelta(minutes=poi.duration_mins)
    
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
        
        # Snap curr to the nearest 15-minute boundary
        discard_mins = curr.minute % 15
        if discard_mins > 0:
            if discard_mins >= 8:
                curr += datetime.timedelta(minutes=(15 - discard_mins))
            else:
                curr -= datetime.timedelta(minutes=discard_mins)
        curr = curr.replace(second=0, microsecond=0)

        while curr + duration_delta <= trip_end:
            slot_start = curr
            slot_end = curr + duration_delta
            curr += datetime.timedelta(minutes=15)  # Step by 15 mins for finer granularity
            
            slot_local = slot_start.astimezone(local_tz)
            slot_time = slot_local.time()
            slot_date = slot_local.strftime("%Y-%m-%d")
            
            earliest_time = datetime.time(7, 0) if is_food else datetime.time(8, 0)
            if slot_time < earliest_time:
                continue
            if slot_time > hard_cap_start and not (poi.ideal_time_end and "23" in poi.ideal_time_end):
                continue
                
            slot_end_local = slot_end.astimezone(local_tz)
            if slot_end_local.date() > slot_local.date() and not (poi.ideal_time_end and "23" in poi.ideal_time_end):
                continue
                
            if getattr(poi, 'valid_days_of_week', None):
                if slot_local.weekday() not in poi.valid_days_of_week:
                    continue
                
            if enforce_ideal_times:
                s_mins = ideal_start_time.hour * 60 + ideal_start_time.minute
                e_mins = ideal_end_time.hour * 60 + ideal_end_time.minute
                
                s_slot = slot_time.hour * 60 + slot_time.minute
                e_slot = slot_end_local.hour * 60 + slot_end_local.minute
                if slot_end_local.date() > slot_local.date():
                    e_slot += 1440
                
                # Add a 15-minute grace period to the ideal window
                if s_slot < (s_mins - 15) or s_slot > (e_mins + 15):
                    continue
                # The end shouldn't be more than 2 hours past the ideal end time
                if e_slot > (e_mins + 120):
                    continue
            
            if poi_hours_start and poi_hours_end:
                slot_end_time = slot_end.astimezone(local_tz).time()
                s_poi_mins = poi_hours_start.hour * 60 + poi_hours_start.minute
                e_poi_mins = poi_hours_end.hour * 60 + poi_hours_end.minute
                
                s_slot = slot_time.hour * 60 + slot_time.minute
                e_slot = slot_end_time.hour * 60 + slot_end_time.minute
                
                if s_slot < s_poi_mins or e_slot > e_poi_mins:
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
                        e_loc_for_routing = e.location
                        poi_loc_for_routing = poi.location
                        
                        if trip.location:
                            if trip.location.lower() not in e.location.lower() and len(e.location.split(',')) < 2:
                                e_loc_for_routing = f"{e.location}, {trip.location}"
                            if trip.location.lower() not in poi.location.lower() and len(poi.location.split(',')) < 2:
                                poi_loc_for_routing = f"{poi.location}, {trip.location}"
                                
                        key = (e_loc_for_routing, poi_loc_for_routing)
                        if key not in location_travel_times:
                            location_travel_times[key] = maps.get_travel_time_minutes(e_loc_for_routing, poi_loc_for_routing)
                        travel_mins = location_travel_times[key]
                        if travel_mins > 60:
                            travel_mins = 0  # Ignore travel time for distant personal events
                
                dynamic_buffer = datetime.timedelta(minutes=travel_mins)
                
                # The slot cannot overlap with the event + the dynamic travel buffer
                if (slot_start - dynamic_buffer) < e.end and (slot_end + dynamic_buffer) > e.start:
                    overlaps = True
                    break
                    
            if overlaps:
                continue
                
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
                            
                if len(non_dessert_food) >= 3:
                    conflict = True
                else:
                    def get_meal_type(t: datetime.time):
                        if t < datetime.time(10, 30): return 'breakfast'
                        elif t < datetime.time(15, 30): return 'lunch'
                        else: return 'dinner'
                        
                    slot_meal = get_meal_type(slot_time)
                    for sp in non_dessert_food:
                        sp_time = datetime.datetime.fromtimestamp(sp.scheduled_start, tz=datetime.timezone.utc).astimezone(local_tz).time()
                        if get_meal_type(sp_time) == slot_meal:
                            conflict = True
                            break
                
                if conflict:
                    continue
                    
            score = 0
            days_from_start = (slot_local.date() - trip_start.astimezone(local_tz).date()).days
            score += max(0, 100 - (days_from_start * 10))
            
            if is_food and not is_dessert:
                if datetime.time(7, 30) <= slot_time <= datetime.time(9, 30):
                    score += 2000
                elif datetime.time(11, 30) <= slot_time <= datetime.time(13, 30):
                    score += 2000
                elif datetime.time(17, 30) <= slot_time <= datetime.time(19, 30):
                    score += 2000
            
            day_home_base = trip.location
            for acc in accommodation_events:
                if acc.start <= slot_start <= acc.end:
                    day_home_base = acc.location
                    break
                    
            if poi.location and day_home_base:
                poi_loc_for_routing = poi.location
                base_loc_for_routing = day_home_base
                if trip.location:
                    if trip.location.lower() not in poi.location.lower() and len(poi.location.split(',')) < 2:
                        poi_loc_for_routing = f"{poi.location}, {trip.location}"
                    if trip.location.lower() not in day_home_base.lower() and len(day_home_base.split(',')) < 2:
                        base_loc_for_routing = f"{day_home_base}, {trip.location}"
                        
                key = (base_loc_for_routing, poi_loc_for_routing)
                if key not in location_travel_times:
                    location_travel_times[key] = maps.get_travel_time_minutes(base_loc_for_routing, poi_loc_for_routing)
                travel_mins_from_base = location_travel_times[key]
                
                if travel_mins_from_base > 180:
                    score -= 10000
                elif travel_mins_from_base > 120:
                    score -= 5000
                elif travel_mins_from_base > 90:
                    score -= 1000
                elif travel_mins_from_base > 60:
                    score -= 500
                elif travel_mins_from_base > 45:
                    score -= 200
                elif travel_mins_from_base > 30:
                    score -= 50
                else:
                    score += 200
            
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
        print('RETURNED SLOTS for', poi.name, ':', slots)
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
                    "label": f"Schedule at {best_alt_start.astimezone(local_tz).strftime('%a %I:%M %p')} (Ignore Ideal Times)"
                })
        
        return None, "Could not find an available time slot matching constraints (e.g. ideal times, overlapping activities, or meal conflicts).", {"suggested_fixes": suggested_fixes}
        
    valid_slots.sort(key=lambda x: (-x[0], x[1]))
    if valid_slots[0][0] < -2000:
        return None, "All available slots require > 2 hours of travel from your home base or other scheduled activities.", None
    best_start = valid_slots[0][1]
        
    best_end = best_start + datetime.timedelta(minutes=poi.duration_mins)
    
    # Always save mock timestamps, bypassing Google Calendar during the planning phase.
    # The actual calendar events will be created when the user clicks 'Commit to Calendar'
    event_id = f"draft_poi_{uuid.uuid4().hex}"
    poi.is_scheduled = True
    poi.scheduled_start = best_start.timestamp()
    poi.scheduled_end = best_end.timestamp()
    poi.event_id = event_id
    return event_id, None, None

from typing import Iterator

def schedule_pois_bulk(trip: TripMetadata, poi_ids: List[str]) -> Iterator[Dict[str, Any]]:
    """
    Schedules multiple POIs at once using a clustering algorithm based on distance and priority.
    Background POIs act as anchors. Regular POIs are assigned to the nearest anchor if within 30 mins travel.
    Standalone regular POIs are spatially clustered.
    Yields a dictionary for each POI: {"poi_id": str, "success": bool, "reason": str}.
    """
    settings = storage.get_settings()
    cals = settings.get('calendar_ids', [])
    
    if not cals:
        for pid in poi_ids:
            yield {"poi_id": pid, "success": False, "reason": "No calendars configured in settings."}
        return
        
    target_pois = [p for p in trip.pois if p.id in poi_ids and not p.is_scheduled]
    if not target_pois:
        return
        
    # Pre-cache distances
    locations = [p.location for p in target_pois if p.location]
    maps.prime_matrix_cache(locations, ignore_age=True)
    
    # Priority sorting mapping
    prio_map = {'must': 3, 'want': 2, 'stretch': 1}
    
    # Separate into anchors (background) and regular
    anchors = [p for p in target_pois if getattr(p, 'is_background', False)]
    regular_pois = [p for p in target_pois if not getattr(p, 'is_background', False)]
    
    anchors.sort(key=lambda x: prio_map.get(x.priority or 'want', 2), reverse=True)
    regular_pois.sort(
        key=lambda x: (
            bool(getattr(x, 'ideal_time_start', None)),
            bool(getattr(x, 'valid_days_of_week', None)),
            prio_map.get(x.priority or 'want', 2)
        ), 
        reverse=True
    )
    
    # Map regular POIs to their closest anchor
    anchor_clusters = {a.id: [] for a in anchors}
    unassigned_pois = []
    
    for rp in regular_pois:
        best_anchor = None
        best_dist = float('inf')
        rp_days = getattr(rp, 'valid_days_of_week', None)
        
        for a in anchors:
            if not rp.location or not a.location: continue
            dist = maps.get_travel_time_minutes(a.location, rp.location)
            
            # Use day match to break ties, but don't override distance
            effective_dist = dist
            if rp_days:
                a_days = getattr(a, 'valid_days_of_week', None)
                if a.scheduled_start:
                    import zoneinfo
                    trip_tz_str = getattr(trip, 'timeZone', None)
                    local_tz = zoneinfo.ZoneInfo(trip_tz_str) if trip_tz_str and trip_tz_str != "UTC" else zoneinfo.ZoneInfo('America/New_York')
                    a_day = datetime.datetime.fromtimestamp(a.scheduled_start, tz=datetime.timezone.utc).astimezone(local_tz).weekday()
                    if a_day not in rp_days:
                        effective_dist += 0.1 # Slight penalty to break ties
                elif a_days:
                    if not any(d in a_days for d in rp_days):
                        effective_dist += 0.1
                        
            if dist <= 30 and effective_dist < best_dist:
                best_dist = effective_dist
                best_anchor = a
                
        if best_anchor:
            anchor_clusters[best_anchor.id].append(rp)
        else:
            unassigned_pois.append(rp)
            
    # Process anchor clusters
    for a in anchors:
        # Schedule the anchor itself
        event_id, reason, meta = schedule_poi(trip, a)
        if event_id:
            yield {"poi_id": a.id, "success": True, "reason": None}
            # Now schedule its attached cluster within its time bounds!
            a_start = datetime.datetime.fromtimestamp(a.scheduled_start, tz=datetime.timezone.utc)
            a_end = datetime.datetime.fromtimestamp(a.scheduled_end, tz=datetime.timezone.utc)
            
            # Sort the cluster by constraint score descending so we schedule the most constrained ones first
            cluster_pois = sorted(
                anchor_clusters[a.id], 
                key=lambda p: (bool(getattr(p, 'ideal_time_start', None)), bool(getattr(p, 'valid_days_of_week', None))), 
                reverse=True
            )
            for rp in cluster_pois:
                rp_event_id, rp_reason, rp_meta = schedule_poi(trip, rp, bounds=(a_start, a_end))
                if rp_event_id:
                    yield {"poi_id": rp.id, "success": True, "reason": None}
                else:
                    # Failed to schedule inside the anchor. Yield as failure so user can resolve it.
                    res = {"poi_id": rp.id, "success": False, "reason": rp_reason}
                    if rp_meta and "suggested_fixes" in rp_meta: res["suggested_fixes"] = rp_meta["suggested_fixes"]
                    yield res
        else:
            # Anchor failed. Drop the cluster into unassigned.
            res = {"poi_id": a.id, "success": False, "reason": reason}
            if meta and "suggested_fixes" in meta: res["suggested_fixes"] = meta["suggested_fixes"]
            yield res
            unassigned_pois.extend(anchor_clusters[a.id])
            
    # Now process standalone clusters from the unassigned pool
    standalone_clusters = []
    for rp in unassigned_pois:
        added = False
        rp_days = getattr(rp, 'valid_days_of_week', None)
        for cluster in standalone_clusters:
            centroid = cluster[0]
            if not rp.location or not centroid.location: continue
            
            c_days = getattr(centroid, 'valid_days_of_week', None)
            if rp_days and c_days and not any(d in c_days for d in rp_days):
                continue
                
            dist = maps.get_travel_time_minutes(centroid.location, rp.location)
            if dist <= 20:
                cluster.append(rp)
                added = True
                break
        if not added:
            standalone_clusters.append([rp])
            
    # Sort the list of clusters so that clusters containing highly constrained POIs are scheduled BEFORE unconstrained clusters!
    standalone_clusters = sorted(
        standalone_clusters,
        key=lambda c: max((bool(getattr(p, 'ideal_time_start', None)), bool(getattr(p, 'valid_days_of_week', None))) for p in c) if c else (False, False),
        reverse=True
    )
    
    for cluster in standalone_clusters:
        if not cluster: continue
        
        # Sort the cluster by constraint score descending so the most constrained POI dictates the day of the cluster!
        cluster = sorted(
            cluster, 
            key=lambda p: (bool(getattr(p, 'ideal_time_start', None)), bool(getattr(p, 'valid_days_of_week', None))), 
            reverse=True
        )
        
        # Schedule the first item normally (no bounds)
        first_poi = cluster[0]
        event_id, reason, meta = schedule_poi(trip, first_poi)
        if event_id:
            yield {"poi_id": first_poi.id, "success": True, "reason": None}
            # Now we know what DAY it landed on. Force the rest to land on the SAME DAY.
            first_start = datetime.datetime.fromtimestamp(first_poi.scheduled_start, tz=datetime.timezone.utc)
            
            import zoneinfo
            trip_tz_str = getattr(trip, 'timeZone', None)
            local_tz = zoneinfo.ZoneInfo(trip_tz_str) if trip_tz_str and trip_tz_str != "UTC" else zoneinfo.ZoneInfo('America/New_York')
            
            first_local = first_start.astimezone(local_tz)
            day_start_local = first_local.replace(hour=0, minute=0, second=0)
            day_end_local = first_local.replace(hour=23, minute=59, second=59)
            
            day_start = day_start_local.astimezone(datetime.timezone.utc)
            day_end = day_end_local.astimezone(datetime.timezone.utc)
            
            for rp in cluster[1:]:
                rp_event_id, rp_reason, rp_meta = schedule_poi(trip, rp, bounds=(day_start, day_end))
                if rp_event_id:
                    yield {"poi_id": rp.id, "success": True, "reason": None}
                else:
                    # If it failed to fit on this day, as a last resort, just schedule it anywhere
                    rp_event_id2, rp_reason2, rp_meta2 = schedule_poi(trip, rp)
                    if rp_event_id2:
                        yield {"poi_id": rp.id, "success": True, "reason": None}
                    else:
                        res = {"poi_id": rp.id, "success": False, "reason": rp_reason2}
                        if rp_meta2 and "suggested_fixes" in rp_meta2: res["suggested_fixes"] = rp_meta2["suggested_fixes"]
                        yield res
        else:
            # First item failed
            res = {"poi_id": first_poi.id, "success": False, "reason": reason}
            if meta and "suggested_fixes" in meta: res["suggested_fixes"] = meta["suggested_fixes"]
            yield res
            
            # Since the first failed and we don't have a day, just schedule the rest normally anywhere
            for rp in cluster[1:]:
                rp_event_id2, rp_reason2, rp_meta2 = schedule_poi(trip, rp)
                if rp_event_id2:
                    yield {"poi_id": rp.id, "success": True, "reason": None}
                else:
                    res = {"poi_id": rp.id, "success": False, "reason": rp_reason2}
                    if rp_meta2 and "suggested_fixes" in rp_meta2: res["suggested_fixes"] = rp_meta2["suggested_fixes"]
                    yield res

    all_scheduled = [p for p in trip.pois if p.is_scheduled and p.scheduled_start]
    by_day = {}
    for p in all_scheduled:
        dt = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        day_str = dt.strftime("%A, %b %d")
        if day_str not in by_day:
            by_day[day_str] = []
        by_day[day_str].append(p)

    insights_yielded = 0
    # Pre-sort POIs per day by scheduled_start
    for day_str in by_day:
        by_day[day_str].sort(key=lambda x: x.scheduled_start)
        
    for p in target_pois:
        if not p.is_scheduled or not p.scheduled_start or not p.location: continue
        if insights_yielded >= 2: break
        
        # We only flag POIs that were heavily constrained by the user
        is_constrained = bool(getattr(p, 'valid_days_of_week', None)) or bool(getattr(p, 'ideal_time_start', None))
        if not is_constrained: continue
        
        p_dt = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        p_day_str = p_dt.strftime("%A, %b %d")
        day_pois = by_day[p_day_str]
        
        idx = day_pois.index(p)
        prev_p = day_pois[idx-1] if idx > 0 else None
        next_p = day_pois[idx+1] if idx < len(day_pois)-1 else None
        
        current_penalty = 0
        if prev_p and prev_p.location: current_penalty += maps.get_travel_time_minutes(prev_p.location, p.location)
        if next_p and next_p.location: current_penalty += maps.get_travel_time_minutes(p.location, next_p.location)
        
        if current_penalty < 15: continue
        
        best_other = None
        best_dist = float("inf")
        for other in all_scheduled:
            if other.id == p.id or not other.location: continue
            other_dt = datetime.datetime.fromtimestamp(other.scheduled_start, tz=datetime.timezone.utc)
            other_day_str = other_dt.strftime("%A, %b %d")
            if other_day_str == p_day_str: continue # Must be a different day
            
            dist = maps.get_travel_time_minutes(other.location, p.location)
            if dist < best_dist:
                best_dist = dist
                best_other = other
                
        if best_other:
            simulated_cost = 2 * best_dist
            savings = current_penalty - simulated_cost
            if savings >= 10:
                other_dt = datetime.datetime.fromtimestamp(best_other.scheduled_start, tz=datetime.timezone.utc)
                other_day_str = other_dt.strftime("%A, %b %d")
                
                yield {
                    "type": "insight",
                    "actionable": True,
                    "poi_id": p.id,
                    "message": f"**{p.name}** was scheduled on {p_day_str} due to your preferences, adding ~{current_penalty} mins of travel. If you clear its constraints, it could be grouped on {other_day_str}, saving ~{savings} mins. Would you like to clear its preferences and reschedule it?",
                    "action_button": "Clear Preferences & Move"
                }
                insights_yielded += 1

def generate_trip_accommodations(trip: TripMetadata, user_prompt: str) -> Tuple[Optional[str], List[TripAccommodation]]:
    """
    Generates suggested accommodations based on the user's prompt and currently scheduled POIs.
    """
    from services.llm import _call_llm_json
    from models.schemas import TripAccommodation
    
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
The user wants to find accommodations (hotels, Airbnbs, chateaus, etc.) for their trip.
Review their scheduled POIs to understand where they will be spending their time, and suggest central accommodations that minimize travel time.
If they have a multi-leg trip (e.g., Paris for 3 days, Countryside for 2 days), suggest an accommodation for each leg, and specify the check-in and check-out dates.

You MUST respond with a single valid JSON object of the following exact structure:
{
  "budget_warning": "Optional string. If you cannot meet the user's budget with these suggestions, populate this warning explaining why and asking where they are willing to compromise. Still generate your best-effort suggestions.",
  "accommodations": [
    {
      "name": "The name of the accommodation (e.g., Ritz Paris)",
      "location": "A search query or address to find this place on a map (e.g. 'Ritz, Paris, France')",
      "notes": "Explain why this is a good fit and what POIs it is close to.",
      "check_in_date": "YYYY-MM-DD",
      "check_out_date": "YYYY-MM-DD",
      "estimated_price_usd": 150.0
    }
  ]
}
Note: `estimated_price_usd` is your best estimate of the TOTAL cost of the stay for the ENTIRE group for the full duration of the trip in USD.
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON.
"""
    
    scheduled_pois = [p for p in trip.pois if p.is_scheduled and p.scheduled_start]
    poi_context = "Scheduled POIs:\n"
    import datetime
    for p in scheduled_pois:
        dt = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc)
        poi_context += f"- {p.name} at {p.location} on {dt.strftime('%Y-%m-%d')}\n"
        
    if not scheduled_pois:
        poi_context = "No POIs scheduled yet.\n"
        
    existing_accs = [a.name for a in trip.accommodations]
    existing_accs_str = ", ".join(existing_accs) if existing_accs else "None"
    
    budget_context = ""
    if getattr(trip, 'budget_max_usd', None) is not None:
        budget_min = getattr(trip, 'budget_min_usd', 0) or 0
        budget_context = f"The user has a target trip budget between ${budget_min} and ${trip.budget_max_usd}. Keep this in mind when estimating prices.\n"
        budget_context += "CRITICAL BUDGET INSTRUCTION: If the total estimated cost of your suggestions exceeds the user's maximum budget, you MUST populate the 'budget_warning' field explaining why and asking where they are willing to compromise. You must STILL provide the best-effort suggestions in the arrays.\n"
        
    travelers = getattr(trip, 'travelers', 1)
    budget_context += f"This trip is for {travelers} traveler(s). Your estimated_price_usd MUST reflect the total cost for the ENTIRE group (not per person) for the entire stay.\n"
        
    if trip.is_draft and trip.mock_start_date:
        trip_start_dt = datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc)
        trip_end_dt = trip_start_dt + datetime.timedelta(days=getattr(trip, 'draft_duration_days', 1))
    else:
        from services.calendar import get_event_dates
        trip_start_dt, trip_end_dt = get_event_dates(trip.event_id)
        if not trip_start_dt or not trip_end_dt:
            trip_start_dt = datetime.datetime.now(datetime.timezone.utc)
            trip_end_dt = trip_start_dt + datetime.timedelta(days=1)
            
    if trip.is_draft:
        date_bounds_str = f"Trip Duration: {getattr(trip, 'draft_duration_days', 1)} days\nNOTE: This is a draft trip being plotted on a mock future calendar year to avoid overlapping with current events.\nThe assigned mock start date is {trip_start_dt.strftime('%Y-%m-%d')} ({trip_start_dt.strftime('%A')}) and the end date is {trip_end_dt.strftime('%Y-%m-%d')} ({trip_end_dt.strftime('%A')}).\nIMPORTANT: Estimate all prices using TODAY'S current prices."
    else:
        date_bounds_str = f"Trip Start Date: {trip_start_dt.strftime('%Y-%m-%d')} ({trip_start_dt.strftime('%A')})\nTrip End Date: {trip_end_dt.strftime('%Y-%m-%d')} ({trip_end_dt.strftime('%A')})"

    user_req = (
        f"Trip Title: {trip.title or 'Unknown'}\n"
        f"Trip Location: {trip.location or 'Unknown'}\n"
        f"{date_bounds_str}\n"
        f"Existing Accommodations: {existing_accs_str}\n"
        f"{poi_context}\n"
        f"{budget_context}"
        f"IMPORTANT: The check_in_date and check_out_date for accommodations MUST fall exactly on or between {trip_start_dt.strftime('%Y-%m-%d')} and {trip_end_dt.strftime('%Y-%m-%d')}. If there is only one accommodation, its check_out_date MUST be exactly {trip_end_dt.strftime('%Y-%m-%d')}.\n"
        f"User Request: {user_prompt}\n"
        f"Generate accommodation suggestions."
    )
    
    try:
        response_json = _call_llm_json(provider, url, api_key, model, system_prompt, user_req, temperature=0.7)
    except Exception as e:
        print(f"Error generating accommodations: {e}")
        return None, []
        
    budget_warning = response_json.get('budget_warning')
    suggestions = response_json.get('accommodations', [])
    accs = []
    
    for s in suggestions:
        name = s.get('name')
        query = s.get('location', name)
        
        enrichment = enrich_poi_data(name, query, trip.location)
            
        acc = TripAccommodation(
            id=uuid.uuid4().hex,
            name=name,
            location=enrichment['location'],
            mapbox_id=enrichment['mapbox_id'],
            lat=enrichment['lat'],
            lng=enrichment['lng'],
            wikidata_id=enrichment['wikidata_id'],
            opening_hours=enrichment['opening_hours'],
            website=enrichment['website'],
            phone_number=enrichment['phone_number'],
            cuisine=enrichment['cuisine'],
            internet_access=enrichment['internet_access'],
            image_url=enrichment['image_url'],
            check_in_date=s.get('check_in_date'),
            check_out_date=s.get('check_out_date'),
            notes=s.get('notes'),
            estimated_price_usd=s.get('estimated_price_usd')
        )
        accs.append(acc)
        
    if getattr(trip, 'budget_max_usd', None):
        total = sum((a.estimated_price_usd or 0) for a in accs)
        if total > trip.budget_max_usd and not budget_warning:
            budget_warning = f"Warning: The total estimated cost of these accommodations (${total:,.2f}) exceeds your maximum budget of ${trip.budget_max_usd:,.2f}. Please review and let me know where you'd like to compromise."
            
    return budget_warning, accs


def generate_trip_plan(trip: 'TripMetadata', user_prompt: str, duration_days: int = 1, proposed_itinerary: str = ""):
    from services.llm import _call_llm_json
    import urllib.parse
    import datetime
    import uuid
    import re
    from models.schemas import TripPOI, TripAccommodation, TripFlight
    from services import storage, maps
    
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
        
    num_pois = max(1, duration_days * 4)
    
    system_prompt = f"""You are an expert travel agent. 
The user will provide a prompt describing what they want to do on their trip.
The user's trip is {duration_days} days long. Your job is to suggest a comprehensive itinerary that fills this trip, including flights, accommodations, and Points of Interest (POIs).
If the user asks for a specific number of places or specific items, you MUST generate exactly what they asked for.
If their request is open-ended, suggest approximately {num_pois} POIs to ensure a full itinerary, 1 or more accommodations based on the trip length, and logical flights if applicable.
CRITICAL: Do NOT put accommodations (like hotels, resorts, or Airbnbs) in the 'pois' array. They MUST go in the 'accommodations' array.

You MUST respond with a single valid JSON object of the following exact structure:
{{
  "budget_warning": "Optional string. If you cannot meet the user's budget with these suggestions, populate this warning explaining why and asking where they are willing to compromise. Still generate your best-effort suggestions.",
  "flights": [
    {{
      "airline": "Delta",
      "flight_number": "DL123",
      "origin": "JFK",
      "destination": "CDG",
      "departure_time": "2026-08-01T18:00:00",
      "arrival_time": "2026-08-02T07:30:00",
      "class_type": "Economy",
      "estimated_price_usd": 850.0,
      "notes": "Direct flight based on preference."
    }}
  ],
  "accommodations": [
    {{
      "name": "The name of the accommodation (e.g., Ritz Paris)",
      "location": "A search query or address to find this place on a map (e.g. 'Ritz, Paris, France')",
      "notes": "Explain why this is a good fit and what POIs it is close to.",
      "check_in_date": "YYYY-MM-DD",
      "check_out_date": "YYYY-MM-DD",
      "estimated_price_usd": 150.0
    }}
  ],
  "pois": [
    {{
      "name": "The name of the location (e.g., French Laundry)",
      "category": "A predefined category string. MUST be one of exactly these: 'sightseeing', 'food', 'activity', 'shopping', or 'other'",
      "description": "A 1-2 sentence compelling description of the experience.",
      "why_picked": "Explain why this specifically matches the user's request (e.g., 'You mentioned wanting a Michelin star experience...').",
      "experience": "Describe what they will actually do there, what the vibe is like, or tips for the visit.",
      "search_query": "The best search query to find this exact place on a map (e.g. 'French Laundry, Yountville, CA')",
      "duration_mins": 90,
      "ideal_time_start": "09:00",
      "ideal_time_end": "12:00",
      "estimated_price_usd": 20.0,
      "is_background": false,
      "valid_days_of_week": [],
      "occurrences": 1
    }}
  ]
}}
`is_background` should be true ONLY if this POI is an umbrella event/location (like a theme park or resort) that spans an entire day or multiple days, and other POIs will be scheduled concurrently inside of it. CRITICAL: For ANY major Theme Park or National Park (e.g. Magic Kingdom, EPCOT, Universal Studios), you MUST set `is_background` to true! Default False. `valid_days_of_week` is an optional array of integers (0=Mon, 6=Sun) representing the ONLY days this POI can be scheduled. CRITICAL: Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6. You MUST map the day name in the proposed itinerary to the exact integer, ignoring relative "Day 1" labels. If the user's prompt mentions preferred days, crowd optimization, or avoiding crowds for specific places, you MUST populate this field with the corresponding day integers (e.g., [1, 2, 4]) to force the solver to schedule it exactly on those days. `occurrences` should be an integer > 1 ONLY if the user explicitly mentions they want to do this activity MULTIPLE times or for MULTIPLE days (e.g., "3 days at Disney" = occurrences: 3). If they say "3 days", you MUST set occurrences to 3. Otherwise default to 1.
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON.
"""

    if trip.is_draft and trip.mock_start_date:
        trip_start_dt = datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc)
        trip_end_dt = trip_start_dt + datetime.timedelta(days=duration_days)
    else:
        from services.calendar import get_event_dates
        trip_start_dt, trip_end_dt = get_event_dates(trip.event_id)
        if not trip_start_dt or not trip_end_dt:
            trip_start_dt = datetime.datetime.now(datetime.timezone.utc)
            trip_end_dt = trip_start_dt + datetime.timedelta(days=duration_days)
    
    if trip.is_draft:
        date_bounds_str = f"Trip Duration: {duration_days} days\nNOTE: This is a draft trip being plotted on a mock future calendar year to avoid overlapping with current events.\nThe assigned mock start date is {trip_start_dt.strftime('%Y-%m-%d')} ({trip_start_dt.strftime('%A')}) and the end date is {trip_end_dt.strftime('%Y-%m-%d')} ({trip_end_dt.strftime('%A')}).\nIMPORTANT: Estimate all prices using TODAY'S current prices. You must strictly use these exact mock dates for any flights or accommodations so it plots correctly on the draft calendar, even if the user asked for different relative days."
    else:
        date_bounds_str = f"Trip Start Date: {trip_start_dt.strftime('%Y-%m-%d')} ({trip_start_dt.strftime('%A')})\nTrip End Date: {trip_end_dt.strftime('%Y-%m-%d')} ({trip_end_dt.strftime('%A')})"
    
    existing_poi_names = [p.name for p in trip.pois] if trip.pois else []
    existing_pois_str = ", ".join(existing_poi_names) if existing_poi_names else "None"
    
    existing_accs = [a.name for a in trip.accommodations] if trip.accommodations else []
    existing_accs_str = ", ".join(existing_accs) if existing_accs else "None"
    
    budget_context = ""
    if getattr(trip, 'budget_max_usd', None) is not None:
        budget_min = getattr(trip, 'budget_min_usd', 0) or 0
        budget_context = f"The user has a target trip budget between ${budget_min} and ${trip.budget_max_usd}. Keep this in mind when estimating prices.\n"
        budget_context += "CRITICAL BUDGET INSTRUCTION: If the total estimated cost of your suggestions (Flights + Accommodations + POIs) exceeds the user's maximum budget, you MUST populate the 'budget_warning' field explaining why and asking where they are willing to compromise. You must STILL provide the best-effort suggestions in the arrays.\n"
    if getattr(trip, 'flight_preferences', None):
        budget_context += f"Flight Preferences: {trip.flight_preferences}\n"
        
    travelers = getattr(trip, 'travelers', 1)
    budget_context += f"This trip is for {travelers} traveler(s). Your estimated_price_usd for flights and accommodations MUST reflect the total cost for the ENTIRE group (not per person).\n"

    home_location_str = f"User's Home Location: {settings.get('home_location')} (Use this as the origin for flights unless specified otherwise)\n" if settings.get('home_location') else ""

    proposed_str = ""
    if proposed_itinerary:
        proposed_str = f"CRITICAL INSTRUCTION: The assistant has already promised the user the following itinerary. You MUST align the POIs, their `valid_days_of_week`, and `ideal_time_start`/`ideal_time_end` exactly with this itinerary so the final schedule matches what the user expects.\nProposed Itinerary: {proposed_itinerary}\n"

    user_req = (
        f"Trip Title: {trip.title or 'Unknown'}\n"
        f"{home_location_str}"
        f"Trip Location: {trip.location or 'Unknown'}\n"
        f"Trip Notes/Context: {trip.notes or 'None'}\n"
        f"{date_bounds_str}\n"
        f"{budget_context}"
        f"IMPORTANT: The check_in_date and check_out_date for accommodations MUST fall exactly on or between {trip_start_dt.strftime('%Y-%m-%d')} and {trip_end_dt.strftime('%Y-%m-%d')}. If there is only one accommodation, its check_out_date MUST be exactly {trip_end_dt.strftime('%Y-%m-%d')}.\n"
        f"Existing POIs (DO NOT suggest these again): {existing_pois_str}\n"
        f"Existing Accommodations (DO NOT suggest these again): {existing_accs_str}\n"
        f"{proposed_str}"
        f"User Request: {user_prompt}\n"
        f"Generate the requested flights, accommodations and POIs, adhering strictly to any quantities specified by the user."
    )
    
    try:
        response_json = _call_llm_json(provider, url, api_key, model, system_prompt, user_req, temperature=0.7)
    except Exception as e:
        print(f"Error generating trip plan: {e}")
        return None, [], [], []
        
    budget_warning = response_json.get('budget_warning')
    sugg_pois = response_json.get('pois', [])
    sugg_accs = response_json.get('accommodations', [])
    sugg_flights = response_json.get('flights', [])
    
    # Keyword check: Move hotel POIs to accommodations
    acc_keywords = ['hotel', 'resort', 'motel', 'inn', 'airbnb', 'hyatt', 'marriott', 'hilton', 'lodge', 'suites', 'villa', 'bnb']
    true_pois = []
    for s in sugg_pois:
        name_lower = s.get('name', '').lower()
        if any(k in name_lower.split() or name_lower.startswith(f"{k} ") or name_lower.endswith(f" {k}") for k in acc_keywords):
            # Move it to sugg_accs if not already there
            if not any(a.get('name') and (s.get('name').lower() in a.get('name').lower() or a.get('name').lower() in s.get('name').lower()) for a in sugg_accs):
                sugg_accs.append({
                    "name": s.get('name'),
                    "location": s.get('location', s.get('name')),
                    "notes": s.get('description', '')
                })
        else:
            true_pois.append(s)
    sugg_pois = true_pois
    
    pois = []
    for s in sugg_pois:
        name = s.get('name')
        
        # Deduplication check against existing POIs
        if any(p.lower() == name.lower() for p in existing_poi_names):
            continue
            
        # Deduplication check against accommodations
        if any(a.get('name') and (name.lower() in a.get('name').lower() or a.get('name').lower() in name.lower()) for a in sugg_accs):
            continue
        if any(acc_name and (name.lower() in acc_name.lower() or acc_name.lower() in name.lower()) for acc_name in existing_accs):
            continue
            
        query = s.get('search_query', name)
        
        enrichment = enrich_poi_data(name, query, trip.location)
        
        occurrences = s.get('occurrences', 1)
        for i in range(occurrences):
            poi_name = name if occurrences == 1 else f"{name} (Day {i+1})"
            poi = TripPOI(
                id=uuid.uuid4().hex,
                name=poi_name,
                location=enrichment['location'],
                mapbox_id=enrichment['mapbox_id'],
                lat=enrichment['lat'],
                lng=enrichment['lng'],
                wikidata_id=enrichment['wikidata_id'],
                opening_hours=enrichment['opening_hours'],
                website=enrichment['website'],
                phone_number=enrichment['phone_number'],
                cuisine=enrichment['cuisine'],
                internet_access=enrichment['internet_access'],
                category=s.get('category', 'other'),
                description=s.get('description'),
                why_picked=s.get('why_picked'),
                experience=s.get('experience'),
                ideal_time_start=s.get('ideal_time_start'),
                ideal_time_end=s.get('ideal_time_end'),
                duration_mins=s.get('duration_mins', 90),
                valid_days_of_week=s.get('valid_days_of_week', []),
                occurrences=1,
                image_url=enrichment['image_url'],
                link=enrichment['link'],
                estimated_price_usd=s.get('estimated_price_usd'),
                is_background=s.get('is_background', False)
            )
            pois.append(poi)

    accs = []
    for s in sugg_accs:
        name = s.get('name')
        
        # Deduplication check
        if any(a.lower() == name.lower() for a in existing_accs):
            continue
            
        query = s.get('location', name)
        
        enrichment = enrich_poi_data(name, query, trip.location)
            
        acc = TripAccommodation(
            id=uuid.uuid4().hex,
            name=name,
            location=enrichment['location'],
            mapbox_id=enrichment['mapbox_id'],
            lat=enrichment['lat'],
            lng=enrichment['lng'],
            wikidata_id=enrichment['wikidata_id'],
            opening_hours=enrichment['opening_hours'],
            website=enrichment['website'],
            phone_number=enrichment['phone_number'],
            cuisine=enrichment['cuisine'],
            internet_access=enrichment['internet_access'],
            image_url=enrichment['image_url'],
            check_in_date=s.get('check_in_date'),
            check_out_date=s.get('check_out_date'),
            notes=s.get('notes'),
            estimated_price_usd=s.get('estimated_price_usd')
        )
        accs.append(acc)
        
    flights = []
    for s in sugg_flights:
        flight = TripFlight(
            id=uuid.uuid4().hex,
            airline=s.get('airline'),
            flight_number=s.get('flight_number'),
            origin=s.get('origin'),
            destination=s.get('destination'),
            departure_time=s.get('departure_time'),
            arrival_time=s.get('arrival_time'),
            class_type=s.get('class_type'),
            estimated_price_usd=s.get('estimated_price_usd'),
            notes=s.get('notes')
        )
        flights.append(flight)
        
    if getattr(trip, 'budget_max_usd', None):
        total = sum((p.estimated_price_usd or 0) for p in pois) + \
                sum((a.estimated_price_usd or 0) for a in accs) + \
                sum((f.estimated_price_usd or 0) for f in flights)
        if total > trip.budget_max_usd and not budget_warning:
            budget_warning = f"Warning: The total estimated cost of this trip (${total:,.2f}) exceeds your maximum budget of ${trip.budget_max_usd:,.2f}. Let me know where you'd like to make concessions (e.g. cheaper hotels, fewer activities) to bring the cost down."
            
    return budget_warning, pois, accs, flights

def suggest_trip_dates(trip: TripMetadata) -> Tuple[Optional[str], Optional[dict]]:
    """
    Analyzes the user's calendar and destination to suggest the optimal trip dates.
    Returns (error_message, suggestion_dict)
    """
    from services.llm import _call_llm_json
    import datetime
    
    settings = storage.get_settings()
    cals = settings.get('calendar_ids', [])
    if not cals:
        return "No calendars configured to analyze your schedule.", None
        
    events = calendar.fetch_upcoming_events(cals, days=365) # 1 year
    
    # Condense events for LLM (date and summary)
    condensed_events = []
    for e in events:
        s_date = e.start.strftime("%Y-%m-%d")
        e_date = e.end.strftime("%Y-%m-%d")
        condensed_events.append(f"{s_date} to {e_date}: {e.summary}")
        
    cal_context = "\n".join(condensed_events) if condensed_events else "No upcoming events found on calendar."
    
    provider = settings.get('llm_provider', 'gemini')
    if provider == 'ollama':
        url = settings.get('llm_ollama_url', 'http://localhost:11434')
        model = settings.get('llm_ollama_model', 'qwen2.5:7b')
        api_key = "ollama"
    else:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        model = settings.get('llm_gemini_model', 'gemini-3.5-flash')
        api_key = settings.get('llm_gemini_api_key')
        
    if not api_key:
        return f"API key not configured for {provider}.", None
        
    duration = trip.draft_duration_days or 3
    start_day = trip.draft_start_day if trip.draft_start_day is not None else 5 # Default Saturday
    days_map = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
    
    system_prompt = f"""
    You are an expert travel agent and executive assistant. 
    Your goal is to suggest the optimal date range for a user's trip.
    
    Constraints:
    1. The trip is to: {trip.location or "Unknown Destination"}
    2. The trip duration is exactly {duration} days.
    3. The trip SHOULD ideally start on a {days_map.get(start_day, "Any day")}.
    4. You must avoid overlapping with the user's existing busy schedule if possible.
    5. You should pick a date range that is historically a good time to visit the destination (e.g. good weather, avoiding monsoon season, etc.) and is at least 2 weeks from today.
    
    Return a JSON object with:
    {{
        "suggested_start_date": "YYYY-MM-DD",
        "suggested_end_date": "YYYY-MM-DD",
        "explanation": "A friendly 2-3 sentence explanation of why you chose these dates, mentioning how it fits their schedule and why it's a good time to visit the destination."
    }}
    """
    
    user_req = f"""
    Current Date: {datetime.datetime.now().strftime('%Y-%m-%d')}
    
    User's Upcoming Calendar Events:
    {cal_context}
    
    Please suggest the best dates for the trip.
    """
    
    try:
        response_json = _call_llm_json(provider, url, api_key, model, system_prompt, user_req, temperature=0.7)
        if "suggested_start_date" in response_json and "suggested_end_date" in response_json:
            return None, response_json
        else:
            return "Failed to parse dates from AI response.", None
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error calling AI: {e}", None
