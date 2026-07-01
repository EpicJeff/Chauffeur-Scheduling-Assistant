import uuid
import datetime
from typing import List, Dict, Any, Optional

from models.schemas import TripMetadata, TripPOI, Event
from services import storage, maps, calendar

def generate_trip_pois(trip: TripMetadata, user_prompt: str) -> List[TripPOI]:
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
Your job is to suggest a list of 3-6 Points of Interest (POIs) that match their request.

You MUST respond with a single valid JSON object of the following exact structure:
{
  "suggestions": [
    {
      "name": "The name of the location (e.g., French Laundry)",
      "category": "A short category string (e.g., 🍷 Vineyard, 🏖️ Beach, 🍽️ Restaurant)",
      "description": "A 1-2 sentence compelling description of the experience.",
      "search_query": "The best search query to find this exact place on a map (e.g. 'French Laundry, Yountville, CA')"
    }
  ]
}
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON.
"""
    
    user_req = f"User Request: {user_prompt}\nTrip Notes/Context: {trip.notes or 'None'}\nGenerate suggestions."
    
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
            
        poi = TripPOI(
            id=uuid.uuid4().hex,
            name=name,
            location=best_location,
            mapbox_id=mapbox_id,
            category=s.get('category'),
            description=s.get('description'),
            duration_mins=90 # Default assumption
        )
        pois.append(poi)
        
    return pois

def schedule_poi(trip: TripMetadata, poi: TripPOI) -> Optional[str]:
    """
    Finds the best open time slot during the trip and schedules the POI in Google Calendar (or isolated environment if draft).
    Returns the event_id if successful, or None if failed.
    """
    settings = storage.get_settings()
    cals = settings.get('calendar_ids', [])
    if not cals:
        return None
        
    if trip.is_draft:
        # Isolated Scheduling Engine
        if not trip.mock_start_date or not trip.mock_end_date:
            return None
        trip_start = datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc)
        trip_end = datetime.datetime.fromtimestamp(trip.mock_end_date, tz=datetime.timezone.utc)
        trip_cals = cals
        
        # Build overlapping events from already scheduled POIs
        overlapping_events = []
        for p in trip.pois:
            if p.is_scheduled and p.id != poi.id and p.scheduled_start and p.scheduled_end:
                class MockEvent:
                    def __init__(self, start, end):
                        self.start = start
                        self.end = end
                overlapping_events.append(MockEvent(
                    datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc),
                    datetime.datetime.fromtimestamp(p.scheduled_end, tz=datetime.timezone.utc)
                ))
    else:
        # Standard Scheduling Engine
        events = calendar.fetch_upcoming_events(cals, days=60)
        trip_event = next((e for e in events if e.id == trip.event_id or trip.event_id in e.source_event_ids), None)
        
        if not trip_event:
            print("Trip event not found, cannot schedule POI.")
            return None
            
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
    
    needed_gap_delta = datetime.timedelta(minutes=poi.duration_mins + 60)
    best_start = None
    
    current_time = trip_start
    if current_time.hour < 9:
        current_time = current_time.replace(hour=9, minute=0, second=0)
        
    for e in overlapping_events:
        gap = e.start - current_time
        if gap >= needed_gap_delta:
            if current_time.hour >= 9 and (current_time + datetime.timedelta(minutes=poi.duration_mins)).hour <= 20:
                best_start = current_time + datetime.timedelta(minutes=30)
                break
        current_time = max(current_time, e.end)
        
    if not best_start:
        gap = trip_end - current_time
        if gap >= needed_gap_delta:
            if current_time.hour >= 9:
                best_start = current_time + datetime.timedelta(minutes=30)
                
    if not best_start:
        best_start = trip_start + (trip_end - trip_start) / 2
        
    best_end = best_start + datetime.timedelta(minutes=poi.duration_mins)
    
    if trip.is_draft:
        # Save mock timestamps, bypass Google Calendar
        event_id = f"draft_poi_{uuid.uuid4().hex}"
        poi.is_scheduled = True
        poi.scheduled_start = best_start.timestamp()
        poi.scheduled_end = best_end.timestamp()
        poi.event_id = event_id
        return event_id
    
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
        
    return event_id
