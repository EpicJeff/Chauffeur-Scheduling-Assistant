import uuid
import datetime
from typing import List, Optional, Dict, Any

def _get_target_element_id(entity_type: str, entity_id: str) -> str:
    """Helper to generate consistent DOM element IDs for UI anchoring."""
    if entity_type == "event":
        return f"event-{entity_id}"
    elif entity_type == "trip_poi":
        return f"poi-{entity_id}"
    return f"generic-{entity_id}"

# ==============================================================================
# CALENDAR TOOLS
# ==============================================================================

def get_calendar_events(start_date: str, end_date: str) -> Dict[str, Any]:
    """
    Retrieves a slimmed-down JSON of calendar events for a specific date range.
    start_date and end_date must be in YYYY-MM-DD format.
    """
    from services.calendar import get_events_for_date_range
    import datetime
    
    start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
    
    events = get_events_for_date_range(start_dt.timestamp(), end_dt.timestamp())
    
    slim_events = []
    for ev in events:
        slim_events.append({
            "id": ev["id"],
            "title": ev["title"],
            "driver_id": ev.get("assigned_driver_id"),
            "start": ev["start"],
            "end": ev["end"]
        })
        
    return {"status": "success", "events": slim_events}


def schedule_calendar_override(event_id: str, driver_id: str, reason: str = "") -> Dict[str, Any]:
    """
    Overrides the scheduled driver for a specific event in the calendar.
    Returns a target_element_id for the UI to anchor a chat bubble.
    """
    from services.calendar import get_event, update_event
    from services.storage import set_manual_override
    
    event = get_event(event_id)
    if not event:
        return {"status": "error", "message": f"Event {event_id} not found."}
        
    # Update DB
    set_manual_override(event_id, driver_id)
    
    target_dom_id = _get_target_element_id("event", event_id)
    
    return {
        "status": "success", 
        "message": f"Successfully assigned driver {driver_id}.",
        "target_element_id": target_dom_id
    }

# ==============================================================================
# TRIP TOOLS
# ==============================================================================

def add_trip_poi(trip_id: str, title: str, start_time: str, duration_mins: int, location: str) -> Dict[str, Any]:
    """
    Adds a new Point of Interest (POI) to a trip's itinerary.
    start_time must be ISO 8601 string.
    Returns a target_element_id for the UI to anchor a chat bubble.
    """
    from services.storage import get_trip_metadata, set_trip_metadata
    from models.schemas import TripPOI
    
    meta = get_trip_metadata(trip_id)
    if not meta:
        return {"status": "error", "message": f"Trip {trip_id} not found."}
        
    new_poi_id = f"poi_{uuid.uuid4().hex[:8]}"
    new_poi = TripPOI(
        id=new_poi_id,
        title=title,
        location=location,
        start_time=start_time,
        duration_mins=duration_mins
    )
    
    if "pois" not in meta:
        meta["pois"] = []
        
    meta["pois"].append(new_poi.model_dump())
    set_trip_metadata(trip_id, meta)
    
    target_dom_id = _get_target_element_id("trip_poi", new_poi_id)
    
    return {
        "status": "success",
        "message": f"Added POI {title} to trip.",
        "target_element_id": target_dom_id
    }

# ==============================================================================
# TOOL REGISTRY (For Gemma Router)
# ==============================================================================

def get_available_tools() -> List[Dict]:
    """
    Returns the JSON schemas for the tools available to the Gemma router.
    """
    return [
        {
            "name": "get_calendar_events",
            "description": "Retrieves calendar events for a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"}
                },
                "required": ["start_date", "end_date"]
            }
        },
        {
            "name": "schedule_calendar_override",
            "description": "Overrides the assigned driver for an event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "driver_id": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["event_id", "driver_id"]
            }
        },
        {
            "name": "add_trip_poi",
            "description": "Adds a Point of Interest to a trip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string"},
                    "title": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO 8601"},
                    "duration_mins": {"type": "integer"},
                    "location": {"type": "string"}
                },
                "required": ["trip_id", "title", "start_time", "duration_mins", "location"]
            }
        }
    ]
