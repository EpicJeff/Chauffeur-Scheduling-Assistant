import json
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class GetCurrentStateTool(BaseModel):
    """
    Retrieves the current state of the Chauffeur schedule, including drivers, passengers, and active rules.
    If date is provided, fetches the schedule for that date. Otherwise, fetches today.
    """
    date: str = Field("", description="The date to fetch the schedule for (YYYY-MM-DD). If omitted or empty, fetches today.")

class AddRoutingRuleTool(BaseModel):
    """
    Creates a new routing rule. Use this for strict constraints (required, excluded), time buffers, tolerances, attendance actions, or to GROUP multiple events together into a single trip.
    """
    driver_id: str = Field(..., description="The ID of the driver this rule applies to.")
    constraint_type: str = Field(..., description="Type of constraint: 'required', 'excluded', 'preferred', 'attendance', 'buffer', 'tolerance', 'duplicate', 'group'.")
    keywords: List[str] = Field(..., description="List of keywords to match against event titles.")
    passenger_ids: List[str] = Field(default=[], description="List of passenger IDs this rule applies to.")
    days_of_week: List[int] = Field(default=[], description="Days of week (0=Mon, 6=Sun). Empty means all days.")
    time_start: str = Field(default="", description="Start time constraint (HH:MM). Empty means anytime.")
    time_end: str = Field(default="", description="End time constraint (HH:MM). Empty means anytime.")
    location: str = Field(default="", description="Location string to match.")
    filter_sets: List[Dict[str, Any]] = Field(default=[], description="For 'group' rules, specify multiple independent event filters here to group events together.")
    attendance_action: str = Field(default="", description="For 'attendance' rules: 'stay' or 'dropoff_pickup'.")
    tolerance_mins: int = Field(default=0, description="For 'tolerance' rules: minutes allowed.")
    tolerance_type: str = Field(default="both", description="For 'tolerance' rules: 'arrival', 'departure', 'both'.")
    buffer_before_mins: int = Field(default=0, description="For 'buffer' rules: minutes before event.")
    buffer_after_mins: int = Field(default=0, description="For 'buffer' rules: minutes after event.")
    duplicate_action: str = Field(default="", description="For 'duplicate' rules: 'schedule_one' or 'schedule_all'.")
    grouping_period: str = Field(default="daily", description="For 'duplicate' rules: 'daily', 'weekly', 'monthly'.")

class DeleteRoutingRuleTool(BaseModel):
    """
    Deletes an existing routing rule by its ID.
    """
    rule_id: str = Field(..., description="The ID of the routing rule to delete.")

class AddPriorityRuleTool(BaseModel):
    """
    Creates a new priority rule to mark an event's relative IMPORTANCE.
    Do NOT use this for grouping events (use AddRoutingRuleTool with constraint_type='group' instead).
    """
    weight_modifier: int = Field(..., description="Score modifier. Use 10000 for critical must-route events. Do NOT use this for 'staying' at an event, that is an attendance rule.")
    keywords: List[str] = Field(..., description="List of keywords to match against event titles.")
    passenger_ids: List[str] = Field(default=[], description="List of passenger IDs this rule applies to.")
    days_of_week: List[int] = Field(default=[], description="Days of week (0=Mon, 6=Sun). Empty means all days.")
    time_start: str = Field(default="", description="Start time constraint (HH:MM). Empty means anytime.")
    time_end: str = Field(default="", description="End time constraint (HH:MM). Empty means anytime.")
    location: str = Field(default="", description="Location string to match.")

class DeletePriorityRuleTool(BaseModel):
    """
    Deletes an existing priority rule by its ID.
    """
    rule_id: str = Field(..., description="The ID of the priority rule to delete.")

class RunSolverTool(BaseModel):
    """
    Triggers the graph scheduling solver to evaluate the current events and rules.
    Always run this after modifying rules to check if your changes created a valid schedule.
    """
    date: str = Field("", description="The date to solve for (YYYY-MM-DD). If omitted or empty, solves today.")

class AddOverrideTool(BaseModel):
    """
    Creates a direct override for a specific event to assign a specific driver.
    This is for one-off manual assignments. It supersedes all routing rules.
    """
    event_id: str = Field(..., description="The ID of the event.")
    driver_id: str = Field(..., description="The ID of the driver to manually assign.")
    date_str: str = Field(..., description="The date of the event (YYYY-MM-DD).")
    event_title: str = Field("", description="Optional title of the event for display purposes. Leave empty if none.")

class DeleteOverrideTool(BaseModel):
    """
    Removes a manual driver assignment for a specific event.
    """
    event_id: str = Field(..., description="The ID of the event to clear the override for.")

class UpdateMemoryTool(BaseModel):
    """
    Saves custom instructions or rules for yourself to remember persistently across sessions. Use this when the user tells you to 'remember' a global preference or instruction.
    """
    memory_text: str = Field(..., description="The complete text of all custom instructions you want to persist.")

class AddErrandTool(BaseModel):
    """
    Adds a new errand to the queue.
    """
    title: str = Field(..., description="The name or title of the errand (e.g. 'Get Groceries').")
    duration_mins: int = Field(..., description="Estimated duration of the errand in minutes.")
    location: str = Field(..., description="The location of the errand.")
    priority: int = Field(default=2, description="Priority: 1 (High), 2 (Medium), 3 (Low).")
    tags: List[str] = Field(default=[], description="List of tags.")
    recurrence_rule: str = Field(default="", description="Recurrence: 'daily', 'weekly', 'monthly', or empty for one-off.")
    starts_on: float = Field(default=0.0, description="Unix timestamp for the anchor/starts-on date. If 0, uses current time.")
    window_days: Optional[int] = Field(default=None, description="Number of valid days to schedule this errand.")
    allowed_drivers: List[str] = Field(default=[], description="List of driver IDs allowed.")
    required_drivers: List[str] = Field(default=[], description="List of driver IDs required (use this if the user says who MUST do the errand).")
    prohibited_drivers: List[str] = Field(default=[], description="List of driver IDs prohibited.")
    allowed_passengers: List[str] = Field(default=[], description="List of passenger IDs allowed.")
    required_passengers: List[str] = Field(default=[], description="List of passenger IDs required.")
    prohibited_passengers: List[str] = Field(default=[], description="List of passenger IDs prohibited.")
    time_window_start: str = Field(default="", description="Start time constraint (HH:MM).")
    time_window_end: str = Field(default="", description="End time constraint (HH:MM).")
    buffer_mins: int = Field(default=0, description="Buffer time in minutes before/after.")
    tolerance_mins: int = Field(default=0, description="Tolerance for late arrival in minutes.")
    group_id: str = Field(default="", description="Group ID to schedule multiple errands together.")

class UpdateErrandTool(BaseModel):
    """
    Updates an existing errand or marks it as completed.
    """
    errand_id: str = Field(..., description="The ID of the errand to update.")
    is_completed: bool = Field(default=False, description="Set to true to mark the errand as completed (this will automatically reschedule it if recurring).")
    title: str = Field(default="", description="Optional new title.")
    duration_mins: int = Field(default=0, description="Optional new duration.")
    location: str = Field(default="", description="Optional new location.")
    starts_on: float = Field(default=0.0, description="Optional new starts_on unix timestamp.")
    allowed_drivers: Optional[List[str]] = Field(default=None, description="Optional List of driver IDs allowed.")
    required_drivers: Optional[List[str]] = Field(default=None, description="Optional List of driver IDs required.")
    prohibited_drivers: Optional[List[str]] = Field(default=None, description="Optional List of driver IDs prohibited.")
    allowed_passengers: Optional[List[str]] = Field(default=None, description="Optional List of passenger IDs allowed.")
    required_passengers: Optional[List[str]] = Field(default=None, description="Optional List of passenger IDs required.")
    prohibited_passengers: Optional[List[str]] = Field(default=None, description="Optional List of passenger IDs prohibited.")
    time_window_start: Optional[str] = Field(default=None, description="Optional Start time constraint (HH:MM).")
    time_window_end: Optional[str] = Field(default=None, description="Optional End time constraint (HH:MM).")
    buffer_mins: Optional[int] = Field(default=None, description="Optional Buffer time in minutes.")
    tolerance_mins: Optional[int] = Field(default=None, description="Optional Tolerance for late arrival.")
    group_id: Optional[str] = Field(default=None, description="Optional Group ID.")

class DeleteErrandTool(BaseModel):
    """
    Deletes an errand completely.
    """
    errand_id: str = Field(..., description="The ID of the errand to delete.")

class GetErrandsTool(BaseModel):
    """
    Gets a list of all active errands.
    """
    pass

class AddErrandRuleTool(BaseModel):
    """
    Creates a new errand rule constraint.
    """
    title: str = Field(..., description="A descriptive title for the rule.")
    constraint_type: str = Field(..., description="Type: 'driver_assignment', 'passenger_assignment', 'time_of_day', 'buffer_tolerance', 'grouping'.")
    location: str = Field(default="", description="Location substring to match.")
    keywords: List[str] = Field(default=[], description="Keywords to match in errand title.")
    keywords_match_all: bool = Field(default=False, description="If True, all keywords must match.")
    allowed_drivers: List[str] = Field(default=[], description="List of driver IDs allowed (optional).")
    required_drivers: List[str] = Field(default=[], description="List of driver IDs required (optional).")
    prohibited_drivers: List[str] = Field(default=[], description="List of driver IDs prohibited (optional).")
    allowed_passengers: List[str] = Field(default=[], description="List of passenger IDs allowed (optional).")
    required_passengers: List[str] = Field(default=[], description="List of passenger IDs required (optional).")
    prohibited_passengers: List[str] = Field(default=[], description="List of passenger IDs prohibited (optional).")
    time_window_start: str = Field(default="", description="Start time constraint (HH:MM).")
    time_window_end: str = Field(default="", description="End time constraint (HH:MM).")
    window_days: Optional[int] = Field(default=None, description="Number of valid days to schedule this errand.")
    buffer_mins: int = Field(default=0, description="Minutes before/after errand.")
    tolerance_mins: int = Field(default=0, description="Tolerance for scheduling outside preferred windows.")
    filter_sets: List[Dict[str, Any]] = Field(default=[], description="For 'grouping' rules, list of filter objects (each with keywords, keywords_match_all, location) to group errands.")

class DeleteErrandRuleTool(BaseModel):
    """
    Deletes an existing errand rule by its doc_id.
    """
    rule_id: str = Field(..., description="The doc_id of the errand rule to delete.")

class SearchPlacesTool(BaseModel):
    """
    Searches for Points of Interest (POIs) or addresses (e.g. 'gas station', 'Target', '123 Main St') near an optional proximity location.
    Use this to find a location before creating an errand if you don't know the exact address.
    """
    query: str = Field(..., description="The name, category, or address to search for (e.g., 'gas station', 'Starbucks').")
    proximity_location: str = Field(default="", description="A known location (address or name) to search near. Usually one of the driver's scheduled stops.")

class GenerateTripPlanTool(BaseModel):
    """
    Generates a complete trip itinerary, including multiple Points of Interest (POIs) and Accommodations, in a single AI pass.
    Always use this when the user asks you to plan a trip, generate ideas for a trip, or suggests a list of things to do on a trip.
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    prompt: str = Field(..., description="The user's preferences for the trip (e.g. 'Michelin star restaurants, bold red wines, sightseeing').")


class AddTripPoiTool(BaseModel):
    """
    Adds a Point of Interest (POI) to a specific Trip. Use this when a user says they want to visit a location during a trip.
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    name: str = Field(..., description="The name of the POI (e.g. 'Eiffel Tower').")
    location: str = Field(..., description="The address/location of the POI.")
    mapbox_id: Optional[str] = Field(default=None, description="The Mapbox ID if found via search_places.")
    category: Optional[str] = Field(default="sightseeing", description="Category (sightseeing, food, activity, shopping, other).")
    duration_mins: int = Field(default=60, description="Duration in minutes.")
    notes: Optional[str] = Field(default="", description="Any notes.")

class EditTripPoiTool(BaseModel):
    """
    Edits the properties of an existing Trip POI. Use this when the user asks you to update a POI's location, name, priority, or duration.
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    poi_id: str = Field(..., description="The ID of the POI to edit.")
    name: Optional[str] = Field(default=None, description="Optional new name.")
    location: Optional[str] = Field(default=None, description="Optional new location/address.")
    category: Optional[str] = Field(default=None, description="Optional new category.")
    duration_mins: Optional[int] = Field(default=None, description="Optional new duration in minutes.")
    priority: Optional[str] = Field(default=None, description="Optional new priority (must, want, stretch).")

class StartDriveTool(BaseModel):
    """Logs a telemetry event that the driver has started a leg, and returns a navigation URL."""
    driver_id: str = Field(..., description="The ID of the driver.")
    event_id: str = Field(..., description="The ID of the event/errand the driver is heading to.")
    destination: str = Field(..., description="The location the driver is heading to.")

class UpdateDriveStatusTool(BaseModel):
    """Updates the completion status of a drive leg or event."""
    event_id: str = Field(..., description="The exact event ID to mark completed.")
    status: str = Field(default="completed", description="The status, usually 'completed'.")
    leg_id: str = Field(default="", description="The exact leg ID if known (e.g. 'route_evt1_evt2').")

# A unified schema registry
TOOL_SCHEMAS = {
    "start_drive": StartDriveTool.model_json_schema(),
    "update_drive_status": UpdateDriveStatusTool.model_json_schema(),
    "get_current_state": GetCurrentStateTool.model_json_schema(),
    "add_routing_rule": AddRoutingRuleTool.model_json_schema(),
    "delete_routing_rule": DeleteRoutingRuleTool.model_json_schema(),
    "add_priority_rule": AddPriorityRuleTool.model_json_schema(),
    "delete_priority_rule": DeletePriorityRuleTool.model_json_schema(),
    "run_solver": RunSolverTool.model_json_schema(),
    "add_override": AddOverrideTool.model_json_schema(),
    "delete_override": DeleteOverrideTool.model_json_schema(),
    "update_memory": UpdateMemoryTool.model_json_schema(),
    "add_errand": AddErrandTool.model_json_schema(),
    "update_errand": UpdateErrandTool.model_json_schema(),
    "delete_errand": DeleteErrandTool.model_json_schema(),
    "get_errands": GetErrandsTool.model_json_schema(),
    "add_errand_rule": AddErrandRuleTool.model_json_schema(),
    "delete_errand_rule": DeleteErrandRuleTool.model_json_schema(),
    "search_places": SearchPlacesTool.model_json_schema(),
    "generate_trip_plan": GenerateTripPlanTool.model_json_schema(),
    "add_trip_poi": AddTripPoiTool.model_json_schema(),
    "edit_trip_poi": EditTripPoiTool.model_json_schema(),
}

def get_openai_tools() -> List[Dict[str, Any]]:
    """Formats schemas for OpenAI/Ollama tool calling API."""
    import copy
    
    def scrub_schema(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get("title"), str):
                obj.pop("title", None)
            obj.pop("additionalProperties", None)
            for k, v in list(obj.items()):
                scrub_schema(v)
        elif isinstance(obj, list):
            for item in obj:
                scrub_schema(item)
        return obj

    tools = []
    for name, schema in TOOL_SCHEMAS.items():
        clean_schema = scrub_schema(copy.deepcopy(schema))
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": clean_schema.get("description", ""),
                "parameters": clean_schema
            }
        })
    return tools

def handle_get_current_state(args: dict) -> dict:
    from services import storage
    state = {
        "drivers": storage.get_all_drivers(),
        "passengers": storage.get_all_passengers(),
        "routing_rules": storage.get_all_rules(),
        "priority_rules": storage.get_all_priority_rules(),
        "overrides": storage.get_all_overrides(),
    }
    date_str = args.get("date")
    if not date_str:
        import datetime
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        
    import main
    res = main.refresh_schedule_logic(date_str, date_str, force_refresh=False)
    
    clean_events = []
    if "events" in res:
        for e in res["events"]:
            # Make sure to only include events for the requested date, just in case
            if e.get("start_date") == date_str:
                clean_e = {k: v for k, v in e.items() if k not in ['polyline', 'distance_matrix', 'steps', 'geometry']}
                clean_events.append(clean_e)
                
    state["schedule"] = clean_events
    return state

def handle_add_routing_rule(args: dict) -> dict:
    from services import storage
    args.setdefault('filter_sets', [])
    args.setdefault('buffer_before_mins', 0)
    args.setdefault('buffer_after_mins', 0)
    args.setdefault('attendance_action', 'stay')
    
    rule_id = storage.add_rule(args)
    return {"status": "success", "rule_id": rule_id}

def handle_delete_routing_rule(args: dict) -> dict:
    from services import storage
    try:
        rule_id = int(args.get("rule_id", 0))
        storage.delete_rule(rule_id)
        return {"status": "success"}
    except ValueError:
        return {"status": "error", "message": "rule_id must be an integer"}

def handle_add_priority_rule(args: dict) -> dict:
    from services import storage
    rule_id = storage.add_priority_rule(args)
    return {"status": "success", "rule_id": rule_id}

def handle_delete_priority_rule(args: dict) -> dict:
    from services import storage
    try:
        rule_id = int(args.get("rule_id", 0))
        storage.delete_priority_rule(rule_id)
        return {"status": "success"}
    except ValueError:
        return {"status": "error", "message": "rule_id must be an integer"}

def handle_run_solver(args: dict) -> dict:
    import main
    date = args.get('date') or None
    res = main.refresh_schedule_logic(date, date, force_refresh=True)
    
    clean_events = []
    if 'events' in res:
        for e in res['events']:
            clean_e = {k: v for k, v in e.items() if k not in ['polyline', 'distance_matrix', 'steps', 'geometry', 'description']}
            clean_events.append(clean_e)
            
    return {
        "status": "success",
        "message": "Solver completed successfully.",
        "schedule": clean_events
    }

def handle_add_override(args: dict) -> dict:
    from services import storage
    import uuid
    override_data = {
        "id": uuid.uuid4().hex,
        "event_id": args.get("event_id"),
        "driver_id": args.get("driver_id"),
        "date_str": args.get("date_str"),
        "event_title": args.get("event_title")
    }
    storage.add_override(override_data)
    return {"status": "success", "message": f"Assigned driver {override_data['driver_id']} to event {override_data['event_id']}."}

def handle_delete_override(args: dict) -> dict:
    from services import storage
    storage.delete_override_by_event(args.get("event_id"))
    return {"status": "success", "message": f"Removed override for event {args.get('event_id')}."}

def handle_update_memory(args: dict) -> dict:
    from services import storage
    settings = storage.get_settings()
    settings['ai_memory'] = args.get("memory_text", "")
    storage.update_settings(settings)
    return {"status": "success", "message": "Memory updated successfully."}

def handle_add_errand(args: dict) -> dict:
    from services import storage
    import time
    starts_on = args.get('starts_on', 0.0)
    if not starts_on: starts_on = time.time()
    errand = {
        'title': args.get('title'),
        'duration_mins': args.get('duration_mins', 30),
        'location': args.get('location'),
        'priority': args.get('priority', 2),
        'tags': args.get('tags', []),
        'recurrence_rule': args.get('recurrence_rule') or None,
        'starts_on': starts_on,
        'created_at': time.time(),
        'is_completed': False,
        'status': 'pending',
        'allowed_drivers': args.get('allowed_drivers', []),
        'required_drivers': args.get('required_drivers', []),
        'prohibited_drivers': args.get('prohibited_drivers', []),
        'allowed_passengers': args.get('allowed_passengers', []),
        'required_passengers': args.get('required_passengers', []),
        'prohibited_passengers': args.get('prohibited_passengers', []),
        'time_window_start': args.get('time_window_start') or None,
        'time_window_end': args.get('time_window_end') or None,
        'buffer_mins': args.get('buffer_mins', 0),
        'tolerance_mins': args.get('tolerance_mins', 0),
        'group_id': args.get('group_id') or None,
        'window_days': args.get('window_days')
    }
    storage.add_errand(errand)
    return {"status": "success", "message": "Errand added."}

def handle_update_errand(args: dict) -> dict:
    from services import storage
    errand_id = args.get('errand_id')
    errand = storage.get_errand(errand_id)
    if not errand: return {"status": "error", "message": "Errand not found."}
    
    if args.get('is_completed'):
        storage.complete_errand(errand_id)
        return {"status": "success", "message": "Errand marked as completed and rescheduled if recurring."}
    
    update_data = {}
    if args.get('title'): update_data['title'] = args.get('title')
    if args.get('duration_mins'): update_data['duration_mins'] = args.get('duration_mins')
    if args.get('location'): update_data['location'] = args.get('location')
    if args.get('starts_on'): update_data['starts_on'] = args.get('starts_on')
    
    for field in ['allowed_drivers', 'required_drivers', 'prohibited_drivers', 
                  'allowed_passengers', 'required_passengers', 'prohibited_passengers']:
        if args.get(field) is not None:
            update_data[field] = args.get(field)
            
    for field in ['time_window_start', 'time_window_end', 'group_id']:
        if args.get(field) is not None:
            update_data[field] = args.get(field) or None
            
    for field in ['buffer_mins', 'tolerance_mins']:
        if args.get(field) is not None:
            update_data[field] = args.get(field)
    
    if update_data:
        storage.update_errand(errand_id, update_data)
        
    return {"status": "success", "message": "Errand updated."}

def handle_delete_errand(args: dict) -> dict:
    from services import storage
    storage.delete_errand(args.get('errand_id'))
    return {"status": "success", "message": "Errand deleted."}

def handle_get_errands(args: dict) -> dict:
    from services import storage
    errands = storage.get_all_errands()
    return {"status": "success", "errands": errands}

def handle_add_errand_rule(args: dict) -> dict:
    from services import storage
    rule_id = storage.add_errand_rule(args)
    return {"status": "success", "rule_id": rule_id}

def handle_delete_errand_rule(args: dict) -> dict:
    from services import storage
    try:
        rule_id = int(args.get("rule_id", 0))
        storage.delete_errand_rule(rule_id)
        return {"status": "success"}
    except ValueError:
        return {"status": "error", "message": "rule_id must be an integer"}

def handle_search_places(args: dict) -> dict:
    from services import maps
    query = args.get("query")
    proximity = args.get("proximity_location") or None
    results = maps.search_places(query, proximity)
    if not results:
        return {"status": "success", "message": "No places found matching the query."}
    return {"status": "success", "results": results}

def handle_generate_trip_plan(args: dict) -> dict:
    from services import storage
    from models.schemas import TripMetadata
    from services.trip_planner import generate_trip_plan
    
    event_id = args.get('event_id')
    user_prompt = args.get('prompt', '')
    
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"status": "error", "message": f"Trip {event_id} not found."}
        
    duration_days = meta.get('draft_duration_days')
    if duration_days is None:
        start_ts = meta.get('mock_start_date')
        end_ts = meta.get('mock_end_date')
        if start_ts and end_ts:
            duration_days = max(1, int((end_ts - start_ts) / 86400) + 1)
        else:
            duration_days = 3
            
    trip_obj = TripMetadata(**meta)
    warning, pois, accs, flights = generate_trip_plan(trip_obj, user_prompt, duration_days)
    
    if 'pois' not in meta:
        meta['pois'] = []
    if 'accommodations' not in meta:
        meta['accommodations'] = []
    if 'flights' not in meta:
        meta['flights'] = []
        
    for poi in pois:
        poi_dict = poi.model_dump() if hasattr(poi, 'model_dump') else poi.dict()
        meta['pois'].append(poi_dict)
        
    for acc in accs:
        acc_dict = acc.model_dump() if hasattr(acc, 'model_dump') else acc.dict()
        meta['accommodations'].append(acc_dict)
        
    for flight in flights:
        flight_dict = flight.model_dump() if hasattr(flight, 'model_dump') else flight.dict()
        meta['flights'].append(flight_dict)
        
    storage.set_trip_metadata(event_id, meta)
    
    res = {
        "status": "success",
        "message": f"Generated and added {len(pois)} POIs, {len(accs)} accommodations, and {len(flights)} flights to the trip."
    }
    if warning:
        res["budget_warning"] = warning
    return res

def handle_add_trip_poi(args: dict) -> dict:
    from services import storage
    event_id = args.get('event_id')
    metadata = storage.get_trip_metadata(event_id) or {"event_id": event_id, "pois": []}
    import uuid
    poi = {
        "id": uuid.uuid4().hex,
        "name": args.get('name'),
        "location": args.get('location'),
        "mapbox_id": args.get('mapbox_id'),
        "category": args.get('category', 'sightseeing'),
        "duration_mins": args.get('duration_mins', 60),
        "notes": args.get('notes', ''),
        "is_scheduled": False,
        "scheduled_start": None,
        "scheduled_end": None
    }
    if 'pois' not in metadata:
        metadata['pois'] = []
    metadata['pois'].append(poi)
    storage.set_trip_metadata(event_id, metadata)
    return {"status": "success", "message": f"Added POI {poi['name']} to Trip {event_id}."}

def handle_edit_trip_poi(args: dict) -> dict:
    from services import storage
    event_id = args.get('event_id')
    poi_id = args.get('poi_id')
    metadata = storage.get_trip_metadata(event_id)
    if not metadata or 'pois' not in metadata:
        return {"status": "error", "message": "Trip not found or has no POIs."}
        
    target_poi = next((p for p in metadata['pois'] if p['id'] == poi_id), None)
    if not target_poi:
        return {"status": "error", "message": "POI not found in this trip."}
        
    for field in ['name', 'location', 'category', 'duration_mins', 'priority']:
        if args.get(field) is not None:
            target_poi[field] = args.get(field)
            
    storage.set_trip_metadata(event_id, metadata)
    return {"status": "success", "message": f"Updated POI {target_poi['name']}."}


def handle_start_drive(args: dict) -> dict:
    from services import storage
    import urllib.parse
    event = {
        "driver_id": args.get("driver_id"),
        "event_id": args.get("event_id"),
        "action": "started driving",
        "location": args.get("destination")
    }
    storage.add_telemetry_event(event)
    dest = urllib.parse.quote(args.get("destination", ""))
    return {
        "status": "success",
        "message": f"Navigation link: https://www.google.com/maps/dir/?api=1&destination={dest}"
    }

def handle_update_drive_status(args: dict) -> dict:
    from services import storage
    leg_id = args.get("leg_id")
    event_id = args.get("event_id")
    status = args.get("status", "completed")
    
    if leg_id:
        storage.mark_drive_status(leg_id, status)
    if event_id:
        storage.mark_drive_status(f"route_{event_id}", status)
        storage.mark_drive_status(f"final_{event_id}", status)
        storage.mark_drive_status(f"route_{event_id}_1", status)
        storage.mark_drive_status(f"route_{event_id}_2", status)
        # We don't know the full route_{prev}_{event} but this covers single legs.

    return {"status": "success", "message": f"Marked drive status as {status}."}

TOOL_HANDLERS = {
    "start_drive": handle_start_drive,
    "update_drive_status": handle_update_drive_status,
    "get_current_state": handle_get_current_state,
    "add_routing_rule": handle_add_routing_rule,
    "delete_routing_rule": handle_delete_routing_rule,
    "add_priority_rule": handle_add_priority_rule,
    "delete_priority_rule": handle_delete_priority_rule,
    "run_solver": handle_run_solver,
    "add_override": handle_add_override,
    "delete_override": handle_delete_override,
    "update_memory": handle_update_memory,
    "add_errand": handle_add_errand,
    "update_errand": handle_update_errand,
    "delete_errand": handle_delete_errand,
    "get_errands": handle_get_errands,
    "add_errand_rule": handle_add_errand_rule,
    "delete_errand_rule": handle_delete_errand_rule,
    "search_places": handle_search_places,
    "generate_trip_plan": handle_generate_trip_plan,
    "add_trip_poi": handle_add_trip_poi,
    "edit_trip_poi": handle_edit_trip_poi,
}

def execute_tool(name: str, args: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"status": "error", "message": f"Unknown tool {name}"}
    try:
        return handler(args)
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
