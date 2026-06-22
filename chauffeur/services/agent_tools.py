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

# A unified schema registry
TOOL_SCHEMAS = {
    "get_current_state": GetCurrentStateTool.model_json_schema(),
    "add_routing_rule": AddRoutingRuleTool.model_json_schema(),
    "delete_routing_rule": DeleteRoutingRuleTool.model_json_schema(),
    "add_priority_rule": AddPriorityRuleTool.model_json_schema(),
    "delete_priority_rule": DeletePriorityRuleTool.model_json_schema(),
    "run_solver": RunSolverTool.model_json_schema(),
    "add_override": AddOverrideTool.model_json_schema(),
    "delete_override": DeleteOverrideTool.model_json_schema(),
    "update_memory": UpdateMemoryTool.model_json_schema(),
}

def get_openai_tools() -> List[Dict[str, Any]]:
    """Formats schemas for OpenAI/Ollama tool calling API."""
    import copy
    
    def scrub_schema(obj):
        if isinstance(obj, dict):
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

TOOL_HANDLERS = {
    "get_current_state": handle_get_current_state,
    "add_routing_rule": handle_add_routing_rule,
    "delete_routing_rule": handle_delete_routing_rule,
    "add_priority_rule": handle_add_priority_rule,
    "delete_priority_rule": handle_delete_priority_rule,
    "run_solver": handle_run_solver,
    "add_override": handle_add_override,
    "delete_override": handle_delete_override,
    "update_memory": handle_update_memory,
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
