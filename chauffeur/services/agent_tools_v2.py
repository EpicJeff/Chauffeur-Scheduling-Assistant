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
    """
    from services.storage import get_cached_schedule
    import re
    from dateutil.parser import parse
    import datetime
    
    sched = get_cached_schedule()
    events = sched.get("events", [])
    
    # Parse dates robustly
    try:
        sd_clean = re.sub(r'(?i)\b(this|next|last|on|the|upcoming)\b\s+', '', start_date).strip()
        ed_clean = re.sub(r'(?i)\b(this|next|last|on|the|upcoming)\b\s+', '', end_date).strip()
        sd = parse(sd_clean, default=datetime.datetime.now()).date()
        ed = parse(ed_clean, default=datetime.datetime.now()).date()
    except Exception:
        return {"status": "error", "message": f"Could not parse dates: {start_date}, {end_date}"}
    
    slim_events = []
    for ev in events:
        ev_start = ev.get("start", "")
        if len(ev_start) >= 10:
            try:
                ev_dt = datetime.datetime.fromisoformat(ev_start.replace('Z', '+00:00')).date()
                if sd <= ev_dt <= ed:
                    slim_events.append({
                        "id": ev.get("id"),
                        "title": ev.get("title"),
                        "location": ev.get("location"),
                        "start": ev.get("start"),
                        "end": ev.get("end")
                    })
            except ValueError:
                pass
        
    return {"status": "success", "events": slim_events}


def assign_driver_to_event_fuzzy(event_name: str, driver_name: str, target_date: str) -> Dict[str, Any]:
    """
    Finds an event by name on a specific date and assigns a driver to it via a manual override.
    target_date must be YYYY-MM-DD.
    """
    from services.storage import add_override, get_all_drivers, get_cached_schedule
    import datetime
    
    sched = get_cached_schedule()
    events = sched.get("events", [])
    
    # Clean and parse the target date robustly
    import re
    from dateutil.parser import parse
    
    target_date_clean = re.sub(r'(?i)\b(this|next|last|on|the|upcoming)\b\s+', '', target_date).strip()
    target_dt = None
    try:
        if target_date_clean.lower() == 'today':
            target_dt = datetime.datetime.now()
        elif target_date_clean.lower() == 'tomorrow':
            target_dt = datetime.datetime.now() + datetime.timedelta(days=1)
        else:
            target_dt = parse(target_date_clean, default=datetime.datetime.now())
    except:
        pass
    
    # Fuzzy match event
    target_event = None
    event_name_lower = event_name.lower().strip()
    
    # Split search name into words, removing common stop words
    stop_words = {"to", "for", "the", "a", "at", "on", "in", "and"}
    search_words = set(w for w in re.findall(r'\w+', event_name_lower) if w not in stop_words)
    
    best_score = 0
    
    for ev in events:
        ev_start = ev.get("start", "")
        if len(ev_start) >= 10:
            match_date = False
            try:
                ev_dt = datetime.datetime.fromisoformat(ev_start.replace('Z', '+00:00'))
                if target_dt:
                    if ev_dt.date() == target_dt.date():
                        match_date = True
                else:
                    if ev_start[:10] == target_date.strip():
                        match_date = True
            except ValueError:
                pass
                    
            if match_date:
                title = ev.get("title", "").lower()
                # Exact or simple substring match gets highest priority
                if event_name_lower in title or title in event_name_lower and len(title) > 3:
                    target_event = ev
                    best_score = 999
                    break
                
                # Word intersection score
                title_words = set(w for w in re.findall(r'\w+', title) if w not in stop_words)
                if search_words and title_words:
                    overlap = len(search_words.intersection(title_words))
                    if overlap > best_score:
                        best_score = overlap
                        target_event = ev
            
    if not target_event:
        return {"status": "error", "message": f"Could not find any event containing '{event_name}' on {target_date}."}
        
    # Fuzzy match driver
    target_driver = None
    driver_name_lower = driver_name.lower().strip()
    drivers = get_all_drivers()
    for d in drivers:
        if driver_name_lower in d.get("name", "").lower() or driver_name_lower == d.get("hashtag", "").lower().replace("#", ""):
            target_driver = d
            break
            
    if not target_driver:
        return {"status": "error", "message": f"Could not find a driver matching '{driver_name}'."}
        
    # Set the override
    override_data = {
        "event_id": target_event["id"],
        "override_type": "driver",
        "driver_id": target_driver["id"]
    }
    add_override(override_data)
    
    target_dom_id = _get_target_element_id("event", target_event["id"])
    
    return {
        "status": "success", 
        "message": f"Successfully assigned {target_driver.get('name')} to drive for '{target_event['title']}'.",
        "target_element_id": target_dom_id,
        "ui_action": "jump_and_reload",
        "target_driver_id": target_driver["id"]
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

def clear_trip_itinerary(trip_id: str, action: str) -> Dict[str, Any]:
    """
    Clears all Points of Interest from a trip itinerary.
    action can be 'unlink' or 'delete'.
    """
    from services.storage import get_trip_metadata, set_trip_metadata
    
    meta = get_trip_metadata(trip_id)
    if not meta:
        return {"status": "error", "message": f"Trip {trip_id} not found."}
        
    activities_to_delete = meta.get("activities", [])
    changed = False
    if "activities" in meta and meta["activities"]:
        meta["activities"] = []
        changed = True
        
    cleared_count = 0
    for poi in meta.get("pois", []):
        if poi.get("is_scheduled") or poi.get("event_id"):
            poi["is_scheduled"] = False
            poi["scheduled_start"] = None
            poi["scheduled_end"] = None
            poi["event_id"] = None
            cleared_count += 1
            changed = True
            
    if changed:
        set_trip_metadata(trip_id, meta)
        
    if action == "delete":
        try:
            from services.calendar import get_calendar_service
            service = get_calendar_service()
            for act_id in activities_to_delete:
                if "::" in act_id:
                    cal_id, raw_id = act_id.split("::", 1)
                    try:
                        service.events().delete(calendarId=cal_id, eventId=raw_id).execute()
                    except Exception as e:
                        pass
        except Exception as e:
            pass
            
    return {
        "status": "success",
        "message": f"Successfully {'deleted' if action == 'delete' else 'unlinked'} {cleared_count} items from the trip itinerary."
    }

def manage_trip_rules(trip_id: str, action: str, rule: Dict[str, Any] = None, rule_id: str = None) -> Dict[str, Any]:
    """
    Create, list, enable/disable, or delete TripRules on a trip.
    Rules shape the itinerary scheduler (see system_capabilities.md 'Trip Itinerary Scheduling').
    """
    from services.storage import get_trip_metadata, set_trip_metadata
    from models.schemas import TripRule

    meta = get_trip_metadata(trip_id)
    if not meta:
        return {"status": "error", "message": f"Trip {trip_id} not found."}
    rules = meta.get('rules', []) or []

    if action == "list":
        if not rules:
            return {"status": "success", "message": "No rules are set on this trip yet.", "rules": []}
        lines = [f"- {r.get('description')} [{r.get('rule_type')}, {r.get('hardness')}, "
                 f"{'enabled' if r.get('is_enabled', True) else 'DISABLED'}] (id: {r.get('id')})"
                 for r in rules]
        return {"status": "success", "message": "Active trip rules:\n" + "\n".join(lines), "rules": rules}

    if action == "create":
        if not rule:
            return {"status": "error", "message": "A 'rule' object is required for create."}
        try:
            if 'hardness' not in rule:
                # keep_clear is a promise of free time — default hard (design §5.3)
                rule['hardness'] = 'hard' if rule.get('rule_type') == 'keep_clear' else 'soft'
            validated = TripRule(**{**rule, "is_ai_generated": True})
        except Exception as e:
            return {"status": "error",
                    "message": f"Invalid rule (fix the fields and retry): {e}"}
        rules.append(validated.model_dump())
        meta['rules'] = rules
        set_trip_metadata(trip_id, meta)
        return {"status": "success",
                "message": f"Rule added: {validated.description} ({validated.rule_type}, {validated.hardness}). "
                           "It will apply the next time the itinerary is scheduled.",
                "rule_id": validated.id}

    if action in ("enable", "disable", "delete"):
        target = next((r for r in rules if r.get('id') == rule_id), None)
        if not target and rule_id:
            target = next((r for r in rules if rule_id.lower() in (r.get('description') or '').lower()), None)
        if not target:
            return {"status": "error", "message": f"Rule '{rule_id}' not found. Use action 'list' to see rule ids."}
        if action == "delete":
            rules.remove(target)
            msg = f"Rule deleted: {target.get('description')}"
        else:
            target['is_enabled'] = (action == "enable")
            msg = f"Rule {'enabled' if action == 'enable' else 'disabled'}: {target.get('description')}"
        meta['rules'] = rules
        set_trip_metadata(trip_id, meta)
        return {"status": "success", "message": msg}

    return {"status": "error", "message": f"Unknown action '{action}'. Use create, list, enable, disable, or delete."}

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
                    "start_date": {"type": "string", "description": "The start date, e.g. 'Monday' or 'July 15'"},
                    "end_date": {"type": "string", "description": "The end date, e.g. 'Friday' or 'July 20'"}
                },
                "required": ["start_date", "end_date"]
            }
        },
        {
            "name": "assign_driver_to_event_fuzzy",
            "description": "Overrides the assigned driver for a specific event by finding it based on a fuzzy name match on a specific date. This is the CORRECT way to assign a driver or override an assignment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the event or a substring of it."},
                    "driver_name": {"type": "string", "description": "The name or role of the driver to assign."},
                    "target_date": {"type": "string", "description": "The date the event occurs, e.g. 'Wednesday' or 'July 15'."}
                },
                "required": ["event_name", "driver_name", "target_date"]
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
        },
        {
            "name": "clear_trip_itinerary",
            "description": "Clears all Points of Interest from a trip itinerary. You MUST ask the user whether they want to 'unlink' or 'delete_from_calendar' before calling this tool, unless they already specified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["unlink", "delete"], "description": "Whether to just unlink the attractions from the trip timeline, or completely delete the events from Google Calendar."}
                },
                "required": ["trip_id", "action"]
            }
        },
        {
            "name": "auto_schedule_trip_itinerary",
            "description": "Automatically bulk-schedules all unscheduled attractions/POIs in the trip. Use this if the user asks you to schedule all their attractions into the itinerary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string"}
                },
                "required": ["trip_id"]
            }
        },
        {
            "name": "manage_trip_rules",
            "description": ("Create, list, enable, disable, or delete scheduling rules for a trip's itinerary. "
                            "Use this whenever the user expresses a scheduling preference or constraint, e.g. "
                            "'keep day 4 clear' (keep_clear), 'nothing before 9am' (template_override with template_start), "
                            "'Epcot on Tuesday' (day_restriction), 'the boat tour must be in the morning' (block_restriction with blocks), "
                            "'keep dinners under $100' (budget_cap with max_usd), 'keep Tuesday light' (day_capacity with max_active_mins), "
                            "'no two parks back-to-back' (spacing with min_gap_days). "
                            "Rules apply on the next itinerary scheduling run."),
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["create", "list", "enable", "disable", "delete"]},
                    "rule_id": {"type": "string", "description": "For enable/disable/delete: the rule id (or a distinctive phrase from its description)."},
                    "rule": {
                        "type": "object",
                        "description": "For create. Fields: description (string, REQUIRED, human-readable), rule_type (REQUIRED: day_restriction|block_restriction|budget_cap|day_capacity|keep_clear|spacing|template_override), poi_ids/categories/keywords (arrays, select which POIs the rule targets; empty = all), days_of_week (ints 0=Mon..6=Sun), trip_days (ints, 1-indexed trip day), blocks (array of breakfast|morning|lunch|afternoon|dinner|evening), max_usd (number), max_active_mins (int), min_gap_days (int), template_start/template_end ('HH:MM'), hardness ('hard'|'soft', default soft; keep_clear defaults hard). Do NOT invent other fields."
                    }
                },
                "required": ["trip_id", "action"]
            }
        }
    ]

def auto_schedule_trip_itinerary(trip_id: str) -> Dict[str, Any]:
    """
    Returns a UI action instructing the frontend to auto schedule all unscheduled POIs.
    """
    return {
        "status": "success",
        "message": "I'm starting the auto-scheduler for your itinerary now! It might take a moment to plot everything based on distances and opening hours.",
        "ui_action": "auto_schedule_trip"
    }
