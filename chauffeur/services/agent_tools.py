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
    Creates a new routing rule. Use this for hard constraints (required, unavailable), soft steering (preferred, avoid), time buffers, tolerances, attendance actions, or to GROUP multiple events together into a single trip.
    """
    driver_id: str = Field(..., description="The ID of the driver this rule applies to.")
    constraint_type: str = Field(..., description="Type of constraint: 'required', 'preferred', 'unavailable', 'avoid', 'attendance', 'buffer', 'tolerance', 'duplicate', 'group'. Use 'unavailable' to forbid a driver outright; use 'avoid' to make them a last resort.")
    keywords: List[str] = Field(..., description="List of keywords to match against the event title and description.")
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
    weight_modifier: int = Field(..., description="Score modifier added to this event's base assignment reward. Scale: 1000 = mild nudge, 100000 = outranks passenger-continuity bonuses, 500000 = near-mandatory. Use 100000 for critical must-route events like doctor appointments. Negative values deprioritize. Do NOT use this for 'staying' at an event, that is an attendance rule.")
    keywords: List[str] = Field(..., description="List of keywords to match against the event title and description.")
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
    prompt: str = Field(..., description="The user's original request.")
    proposed_itinerary: str = Field(default="", description="If you proposed a specific day-by-day itinerary to the user in your response, provide the full text of that itinerary here so the background planner can align the scheduled days/times exactly with what you told the user.")

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
    occurrences: Optional[int] = Field(default=1, description="Number of times to add this standalone POI (e.g. 'two surf lessons'). NOT for multi-day anchors — use days_claimed.")
    is_background: Optional[bool] = Field(default=False, description="True only for an ANCHOR: a half-day-or-longer experience worth organizing a whole day around (theme park, 'explore the old town'). Never for a single attraction under ~3 hours. Anchors are containers, not summaries: also add each named sight the anchor covers as its own POI with parent_container set to the anchor, or those sights are invisible to the itinerary.")
    days_claimed: Optional[int] = Field(default=1, description="Anchors only: number of FULL DAYS this anchor occupies ('3 days at Disney' = one POI with days_claimed 3).")
    parent_container: Optional[str] = Field(default=None, description="If this POI is inside or part of an anchor (background) POI on the trip, that anchor's name or id. Links the sight to its day container so it schedules on the anchor's claimed days.")
    approx_lat: Optional[float] = Field(default=None, description="Your best estimate of the POI's latitude (region-level accuracy). Used to reject a map match in the wrong city — always provide it.")
    approx_lng: Optional[float] = Field(default=None, description="Your best estimate of the POI's longitude. Always provide it with approx_lat.")
    valid_days_of_week: Optional[List[int]] = Field(default_factory=list, description="List of valid days (0=Mon, 6=Sun) to schedule this POI.")

class AddTripAccommodationTool(BaseModel):
    """
    Adds an Accommodation to a specific Trip. Use this when a user says they are staying at a specific hotel, resort, or Airbnb.
    For a multi-leg trip (e.g. '4 days in Paris, then 3 days in wine country, then 2 days at the coast'), add ONE accommodation
    per leg and set check_in_night/nights so the stays are consecutive and non-overlapping (leg 2 checks in the night leg 1
    checks out). The scheduler uses each day's accommodation as that day's home base, so POIs cluster to the correct leg
    automatically. If no dates/nights are given, the stay spans the whole trip.
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    name: str = Field(..., description="The name of the Accommodation (e.g. 'Hyatt Place').")
    location: str = Field(..., description="The address/location of the Accommodation.")
    mapbox_id: Optional[str] = Field(default=None, description="The Mapbox ID if found via search_places.")
    check_in_night: Optional[int] = Field(default=None, description="1-indexed trip night to check in (night 1 = first night of the trip). Preferred over absolute dates for draft trips.")
    nights: Optional[int] = Field(default=None, description="Number of nights for this stay. Used with check_in_night.")
    check_in_date: Optional[str] = Field(default=None, description="Absolute check-in date YYYY-MM-DD. Only use when the user gave explicit calendar dates; otherwise prefer check_in_night/nights.")
    check_out_date: Optional[str] = Field(default=None, description="Absolute check-out date YYYY-MM-DD.")
    approx_lat: Optional[float] = Field(default=None, description="Your best estimate of the accommodation's latitude (city-level accuracy). Used to reject a map match in the wrong city — always provide it.")
    approx_lng: Optional[float] = Field(default=None, description="Your best estimate of the accommodation's longitude. Always provide it with approx_lat.")
    notes: Optional[str] = Field(default="", description="Any notes.")

class EditTripAccommodationTool(BaseModel):
    """
    Edits an existing Trip Accommodation — use it to change stay dates (e.g. to split a trip into legs), name, location, or notes.
    Identify the accommodation by accommodation_id, or by name (exact or unambiguous partial match).
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    accommodation_id: Optional[str] = Field(default=None, description="The ID of the accommodation to edit, if known.")
    name: Optional[str] = Field(default=None, description="Name of the accommodation to edit (used to find it when accommodation_id is not given).")
    new_name: Optional[str] = Field(default=None, description="New name, if renaming.")
    location: Optional[str] = Field(default=None, description="New address/location, if moving.")
    check_in_night: Optional[int] = Field(default=None, description="1-indexed trip night to check in (night 1 = first night of the trip).")
    nights: Optional[int] = Field(default=None, description="Number of nights for this stay. Used with check_in_night.")
    check_in_date: Optional[str] = Field(default=None, description="Absolute check-in date YYYY-MM-DD (prefer check_in_night for drafts).")
    check_out_date: Optional[str] = Field(default=None, description="Absolute check-out date YYYY-MM-DD.")
    approx_lat: Optional[float] = Field(default=None, description="When changing location: your estimate of the new latitude, to reject a map match in the wrong city.")
    approx_lng: Optional[float] = Field(default=None, description="When changing location: your estimate of the new longitude.")
    notes: Optional[str] = Field(default=None, description="New notes.")

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
    approx_lat: Optional[float] = Field(default=None, description="When changing location: your estimate of the new latitude, to reject a map match in the wrong city.")
    approx_lng: Optional[float] = Field(default=None, description="When changing location: your estimate of the new longitude.")
    valid_days_of_week: Optional[List[int]] = Field(default=None, description="Optional list of integers representing valid days (0=Mon, 6=Sun).")

class GenerateTripFlightsTool(BaseModel):
    """
    Generates and adds realistic round-trip flight suggestions to a Trip in one step, using the
    configured home location as the origin and the trip's destination and dates. ALWAYS use this when
    the user asks to add, suggest, or find flights WITHOUT giving specific flight details — do NOT ask
    them for flight numbers, times, or airports first. The flights are added as editable estimates.
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    prompt: str = Field(default="", description="The user's request verbatim, including any stated origin, airline, or cabin preferences. Empty is fine for a bare 'add flights'.")

class AddTripFlightTool(BaseModel):
    """
    Adds a single specific flight to a Trip. Use this when the user provides the flight's details
    (route and day/time, e.g. a flight they already booked). If the user asks for flights WITHOUT
    details, use generate_trip_flights instead — never interrogate them for details.
    On draft trips give times as departure_day/arrival_day trip-day ordinals with 'HH:MM' — the draft's
    mock calendar dates are an implementation detail and must never be shown to the user.
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    origin: str = Field(..., description="Origin airport code or city (e.g. 'JFK' or 'New York').")
    destination: str = Field(..., description="Destination airport code or city.")
    airline: Optional[str] = Field(default=None, description="Airline name (e.g. 'Delta').")
    flight_number: Optional[str] = Field(default=None, description="Flight number (e.g. 'DL123'), if known.")
    departure_day: Optional[int] = Field(default=None, description="1-indexed trip day of departure (day 1 = the trip's arrival day). 0 = the day BEFORE the trip starts (overnight outbound legs). Preferred over ISO datetimes for drafts.")
    departure_time: Optional[str] = Field(default=None, description="Departure time 'HH:MM' 24h (paired with departure_day), or a full ISO datetime 'YYYY-MM-DDTHH:MM:SS' when the user gave explicit calendar dates.")
    arrival_day: Optional[int] = Field(default=None, description="1-indexed trip day of arrival. Overnight flights usually land the day AFTER departure_day.")
    arrival_time: Optional[str] = Field(default=None, description="Arrival time 'HH:MM' 24h (paired with arrival_day), or a full ISO datetime.")
    class_type: Optional[str] = Field(default=None, description="Cabin class (e.g. 'Economy', 'Business').")
    estimated_price_usd: Optional[float] = Field(default=None, description="Estimated total price for the WHOLE travel party in USD.")
    notes: Optional[str] = Field(default="", description="Any notes (layovers, seat preference, booking status).")

class EditTripFlightTool(BaseModel):
    """
    Edits an existing flight on a Trip — times, airline, route, class, price, or notes.
    Identify the flight by flight_id (preferred), by flight_number, or by origin/destination (must match
    exactly one flight). Only the fields you provide are changed; use new_origin/new_destination/
    new_flight_number to change those values. On draft trips prefer departure_day/arrival_day trip-day
    ordinals — mock calendar dates must never be shown to the user.
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    flight_id: Optional[str] = Field(default=None, description="The ID of the flight to edit, if known.")
    flight_number: Optional[str] = Field(default=None, description="Flight number used to FIND the flight when flight_id is not given.")
    origin: Optional[str] = Field(default=None, description="Origin used to FIND the flight when flight_id/flight_number are not given.")
    destination: Optional[str] = Field(default=None, description="Destination used to FIND the flight when flight_id/flight_number are not given.")
    new_flight_number: Optional[str] = Field(default=None, description="New flight number, if changing it.")
    new_origin: Optional[str] = Field(default=None, description="New origin, if changing it.")
    new_destination: Optional[str] = Field(default=None, description="New destination, if changing it.")
    airline: Optional[str] = Field(default=None, description="New airline name.")
    departure_day: Optional[int] = Field(default=None, description="New 1-indexed trip day of departure (0 = day before the trip).")
    departure_time: Optional[str] = Field(default=None, description="New departure time 'HH:MM' (paired with departure_day or the flight's existing date), or a full ISO datetime.")
    arrival_day: Optional[int] = Field(default=None, description="New 1-indexed trip day of arrival.")
    arrival_time: Optional[str] = Field(default=None, description="New arrival time 'HH:MM', or a full ISO datetime.")
    class_type: Optional[str] = Field(default=None, description="New cabin class.")
    estimated_price_usd: Optional[float] = Field(default=None, description="New estimated total price in USD for the whole party.")
    notes: Optional[str] = Field(default=None, description="New notes.")

class DeleteTripFlightTool(BaseModel):
    """
    Deletes a flight from a Trip. Identify it by flight_id (preferred), by flight_number, or by
    origin/destination (must match exactly one flight).
    """
    event_id: str = Field(..., description="The event ID of the Trip.")
    flight_id: Optional[str] = Field(default=None, description="The ID of the flight to delete, if known.")
    flight_number: Optional[str] = Field(default=None, description="Flight number used to find the flight.")
    origin: Optional[str] = Field(default=None, description="Origin used to find the flight.")
    destination: Optional[str] = Field(default=None, description="Destination used to find the flight.")

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

class GetPointBalancesTool(BaseModel):
    """
    Gets the current chore-point balance for every child, sorted highest first.
    """
    pass

class AdjustPointsTool(BaseModel):
    """
    Adds, subtracts, or sets a child's chore points (a parent-level manual adjustment recorded in the points history). Use delta for relative changes ('give Bob 20 points' -> delta 20, 'take away 5' -> delta -5) or set_to for an absolute balance ('set Bob to 100'). Provide exactly one of delta / set_to.
    """
    member_name: str = Field(..., description="The child's name.")
    delta: Optional[int] = Field(default=None, description="Relative point change; negative to subtract.")
    set_to: Optional[int] = Field(default=None, description="Absolute target balance.")
    note: str = Field(default="", description="Short reason shown in the points history, e.g. 'Helped carry groceries'.")

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
    "add_trip_accommodation": AddTripAccommodationTool.model_json_schema(),
    "edit_trip_accommodation": EditTripAccommodationTool.model_json_schema(),
    "edit_trip_poi": EditTripPoiTool.model_json_schema(),
    "generate_trip_flights": GenerateTripFlightsTool.model_json_schema(),
    "add_trip_flight": AddTripFlightTool.model_json_schema(),
    "edit_trip_flight": EditTripFlightTool.model_json_schema(),
    "delete_trip_flight": DeleteTripFlightTool.model_json_schema(),
    "get_point_balances": GetPointBalancesTool.model_json_schema(),
    "adjust_points": AdjustPointsTool.model_json_schema(),
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
    proposed_itinerary = args.get('proposed_itinerary', '')
    
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"status": "error", "message": f"Trip {event_id} not found."}
        
    duration_nights = meta.get('draft_duration_nights')
    if duration_nights is None:
        start_ts = meta.get('mock_start_date')
        end_ts = meta.get('mock_end_date')
        if start_ts and end_ts:
            duration_nights = max(1, int((end_ts - start_ts) / 86400) + 1)
        else:
            duration_nights = 3
            
    trip_obj = TripMetadata(**meta)
    warning, pois, accs, flights = generate_trip_plan(trip_obj, user_prompt, duration_nights, proposed_itinerary)
    
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
    from services.trip_planner import enrich_poi_data
    event_id = args.get('event_id')
    metadata = storage.get_trip_metadata(event_id) or {"event_id": event_id, "pois": []}
    import uuid
    
    name = args.get('name')
    location = args.get('location')
    trip_location = metadata.get('location', '')
    
    enrichment = enrich_poi_data(name, location, trip_location)
    from services.trip_validation import vet_poi, reground_area_anchors
    is_bg, days_claimed, occurrences = vet_poi(enrichment, args)

    parent_id = None
    if not is_bg:  # anchors have no parents
        parent_id = _resolve_parent_anchor(args.get('parent_container'), metadata.get('pois') or [])

    pois_to_add = []
    for i in range(occurrences):
        name_label = name if occurrences == 1 else f"{name} ({i+1} of {occurrences})"
        poi = {
            "id": uuid.uuid4().hex,
            "name": name_label,
            "location": enrichment.get('location') or location,
            "mapbox_id": enrichment.get('mapbox_id') or args.get('mapbox_id'),
            "category": args.get('category', 'sightseeing'),
            "duration_mins": args.get('duration_mins', 60),
            "notes": args.get('notes', ''),
            "is_scheduled": False,
            "scheduled_start": None,
            "scheduled_end": None,
            "occurrences": 1,
            "is_background": is_bg,
            "days_claimed": days_claimed if is_bg else 1,
            "parent_container": parent_id,
            "valid_days_of_week": args.get('valid_days_of_week', [])
        }

        for k, v in enrichment.items():
            if k not in ['location', 'mapbox_id'] and k not in poi:
                poi[k] = v

        pois_to_add.append(poi)

    if 'pois' not in metadata:
        metadata['pois'] = []
    metadata['pois'].extend(pois_to_add)
    # A new child moves its area anchor's centroid — re-ground before saving so
    # the map is right immediately, not only after the next solve.
    reground_area_anchors(metadata['pois'])
    storage.set_trip_metadata(event_id, metadata)

    msg = f"Added {occurrences} POI(s) '{name}' to trip."
    if args.get('is_background') and not is_bg:
        msg += " Note: added as a regular POI, not a day anchor — it lasts under 3 hours."
    if args.get('parent_container') and not is_bg and not parent_id:
        msg += f" Note: no anchor matching '{args.get('parent_container')}' was found — the POI is not linked to a day container."
    return {"status": "success", "message": msg}


def _resolve_parent_anchor(raw, pois):
    """Anchor name-or-id -> anchor id, with the same fuzzy-name semantics as the
    planner's _resolve_parent_containers. None when nothing matches."""
    if not raw:
        return None
    raw_l = str(raw).lower().strip()
    for a in pois:
        if not a.get('is_background'):
            continue
        a_name = (a.get('name') or '').lower().strip()
        if a.get('id') == raw or (a_name and (raw_l == a_name or raw_l in a_name or a_name in raw_l)):
            return a.get('id')
    return None

def _trip_date_bounds(metadata):
    """The trip's (start, end) datetimes: mock window for drafts, calendar
    event dates otherwise. Either may be None."""
    import datetime
    if metadata.get('is_draft') and metadata.get('mock_start_date'):
        start = datetime.datetime.fromtimestamp(metadata['mock_start_date'], tz=datetime.timezone.utc)
        if metadata.get('mock_end_date'):
            end = datetime.datetime.fromtimestamp(metadata['mock_end_date'], tz=datetime.timezone.utc)
        else:
            end = start + datetime.timedelta(days=metadata.get('draft_duration_nights') or 1)
        return start, end
    if not metadata.get('is_draft'):
        from services.calendar import get_event_dates
        return get_event_dates(metadata.get('event_id'))
    return None, None


def _resolve_stay_dates(args, metadata):
    """Resolve an accommodation stay to (check_in, check_out) YYYY-MM-DD strings.

    Priority: explicit dates > 1-indexed trip-night ordinals (night 1 = the
    trip's first night, so night N = trip start + N-1 days) > full trip span
    (the historical default). Ordinal-derived stays are clamped to the trip
    window; explicit dates are trusted as given. Returns "" when unknowable.
    """
    import datetime
    start_dt, end_dt = _trip_date_bounds(metadata)
    start_d = start_dt.date() if start_dt else None
    end_d = end_dt.date() if end_dt else None

    def parse(s):
        try:
            return datetime.datetime.strptime(s, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return None

    ci_d = parse(args.get('check_in_date'))
    co_d = parse(args.get('check_out_date'))
    night = args.get('check_in_night')
    nights = args.get('nights')

    if ci_d is None and night and start_d:
        ci_d = start_d + datetime.timedelta(days=int(night) - 1)
    if ci_d is None:
        ci_d = start_d
    if co_d is None and ci_d and nights:
        co_d = ci_d + datetime.timedelta(days=int(nights))
    if co_d is None:
        co_d = end_d
    if co_d and end_d and co_d > end_d and not args.get('check_out_date'):
        co_d = end_d
    return (ci_d.strftime('%Y-%m-%d') if ci_d else ""), (co_d.strftime('%Y-%m-%d') if co_d else "")


def _night_ordinal(date_str, metadata):
    """1-indexed trip night for a YYYY-MM-DD date, or None."""
    import datetime
    start_dt, _ = _trip_date_bounds(metadata)
    if not start_dt:
        return None
    try:
        d = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    return (d - start_dt.date()).days + 1


def _stay_label(ci, co, metadata):
    """Agent-facing label for a stay range. Draft trips speak in trip nights —
    their mock calendar dates must never surface anywhere a user could see."""
    if metadata.get('is_draft'):
        a, b = _night_ordinal(ci, metadata), _night_ordinal(co, metadata)
        if a is not None and b is not None:
            return f"night {a}" if b - a == 1 else f"nights {a}-{b - 1}"
    return f"{ci} -> {co}"


def _validate_stay(ci, co, metadata, exclude_id=None):
    """Error string if a stay range is invalid or overlaps an existing stay, else None.

    Overlapping stays poison the scheduler's day->home-base map, so the agent
    gets a correctable error instead of a silent write."""
    from services.trip_validation import parse_stay_range, find_stay_overlap
    rng = parse_stay_range(ci, co)
    if rng and rng[1] <= rng[0]:
        return "Check-out must be after check-in — a stay needs at least one night."
    conflict = find_stay_overlap(ci, co, metadata.get('accommodations'), exclude_id=exclude_id)
    if conflict is not None:
        return (f"The requested stay ({_stay_label(ci, co, metadata)}) overlaps the existing stay "
                f"'{conflict.get('name')}' ({_stay_label(conflict.get('check_in_date'), conflict.get('check_out_date'), metadata)}). "
                f"Legs must be contiguous and non-overlapping — shorten that stay first with "
                f"edit_trip_accommodation, or choose non-overlapping check_in_night/nights.")
    return None


def _clip_neighbors(new_ci, new_co, metadata, exclude_id):
    """Make room for an edited stay: clip other stays out of [new_ci, new_co).

    An edit expresses fresh user intent, so neighboring stays yield — their
    dates are clipped to the edited range's edges (rejecting edits outright
    would deadlock: two full-span stays could never be re-dated into legs).
    A stay whose entire range falls inside the edited one cannot be clipped;
    that returns an error instead — deleting a stay must be the agent's
    explicit call, never a side effect. Returns (clip_notes, error)."""
    from services.trip_validation import parse_stay_range
    rng = parse_stay_range(new_ci, new_co)
    if rng is None:
        return [], None
    ci, co = rng
    notes = []
    for a in metadata.get('accommodations') or []:
        if a.get('id') == exclude_id:
            continue
        arng = parse_stay_range(a.get('check_in_date'), a.get('check_out_date'))
        if not arng or not (arng[0] < co and ci < arng[1]):
            continue
        if ci <= arng[0] and arng[1] <= co:
            return [], (f"Those dates would fully cover the existing stay '{a.get('name')}' "
                        f"({_stay_label(a.get('check_in_date'), a.get('check_out_date'), metadata)}). "
                        f"Delete or re-date that stay first.")
        if arng[0] < ci:
            a['check_out_date'] = ci.strftime('%Y-%m-%d')
        else:
            a['check_in_date'] = co.strftime('%Y-%m-%d')
        notes.append(f"'{a.get('name')}' is now "
                     f"{_stay_label(a.get('check_in_date'), a.get('check_out_date'), metadata)}")
    return notes, None


def handle_add_trip_accommodation(args: dict) -> dict:
    from services import storage
    from services.trip_planner import enrich_poi_data
    from services.trip_validation import vet_accommodation
    event_id = args.get('event_id')
    metadata = storage.get_trip_metadata(event_id) or {"event_id": event_id, "pois": [], "accommodations": []}
    import uuid

    name = args.get('name')
    location = args.get('location')
    trip_location = metadata.get('location', '')

    enrichment = enrich_poi_data(name, location, trip_location)
    vet_accommodation(enrichment, args)

    check_in_date, check_out_date = _resolve_stay_dates(args, metadata)
    err = _validate_stay(check_in_date, check_out_date, metadata)
    if err:
        return {"status": "error", "message": err}

    acc = {
        "id": uuid.uuid4().hex,
        "name": name,
        "location": enrichment.get('location') or location,
        "mapbox_id": enrichment.get('mapbox_id') or args.get('mapbox_id'),
        "lat": enrichment.get('lat'),
        "lng": enrichment.get('lng'),
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "notes": args.get('notes', '')
    }
    
    if "accommodations" not in metadata:
        metadata["accommodations"] = []
    metadata["accommodations"].append(acc)
    
    storage.set_trip_metadata(event_id, metadata)
    
    if acc['check_in_date'] and acc['check_out_date']:
        span = _stay_label(acc['check_in_date'], acc['check_out_date'], metadata)
    else:
        span = "no dates"
    return {
        "status": "success",
        "message": f"Added Accommodation '{name}' to trip ({span})."
    }

def handle_edit_trip_accommodation(args: dict) -> dict:
    from services import storage
    event_id = args.get('event_id')
    metadata = storage.get_trip_metadata(event_id)
    if not metadata or not metadata.get('accommodations'):
        return {"status": "error", "message": "Trip not found or has no accommodations."}

    accs = metadata['accommodations']
    acc = None
    if args.get('accommodation_id'):
        acc = next((a for a in accs if a.get('id') == args['accommodation_id']), None)
    if acc is None and args.get('name'):
        name_l = args['name'].strip().lower()
        exact = [a for a in accs if (a.get('name') or '').strip().lower() == name_l]
        partial = [a for a in accs if name_l in (a.get('name') or '').strip().lower()]
        matches = exact or partial
        if len(matches) > 1:
            names = ", ".join(a.get('name', '?') for a in matches)
            return {"status": "error",
                    "message": f"Multiple accommodations match '{args['name']}': {names}. Use accommodation_id."}
        acc = matches[0] if matches else None
    if acc is None:
        return {"status": "error", "message": "Accommodation not found."}

    # resolve and validate any date change BEFORE mutating anything, so a
    # rejected edit leaves the stay untouched
    new_ci = new_co = None
    clip_notes = []
    if any(args.get(k) is not None for k in ('check_in_date', 'check_out_date', 'check_in_night', 'nights')):
        from services.trip_validation import parse_stay_range
        res_args = dict(args)
        # keep the current dates as the baseline unless an ordinal overrides them
        if not res_args.get('check_in_date') and not res_args.get('check_in_night'):
            res_args['check_in_date'] = acc.get('check_in_date')
        if not res_args.get('check_out_date') and not res_args.get('nights'):
            res_args['check_out_date'] = acc.get('check_out_date')
        new_ci, new_co = _resolve_stay_dates(res_args, metadata)
        rng = parse_stay_range(new_ci, new_co)
        if rng and rng[1] <= rng[0]:
            return {"status": "error",
                    "message": "Check-out must be after check-in — a stay needs at least one night."}
        clip_notes, err = _clip_neighbors(new_ci, new_co, metadata, acc.get('id'))
        if err:
            return {"status": "error", "message": err}

    if args.get('new_name'):
        acc['name'] = args['new_name']
    if args.get('location'):
        from services.trip_planner import enrich_poi_data
        from services.trip_validation import reconcile_coords
        enrichment = enrich_poi_data(acc.get('name'), args['location'], metadata.get('location', ''))
        reconcile_coords(enrichment, {'name': acc.get('name'), 'location': args['location'],
                                      'approx_lat': args.get('approx_lat'),
                                      'approx_lng': args.get('approx_lng')})
        # the old coords/ids described the old location — replace, never keep stale
        acc['location'] = enrichment.get('location') or args['location']
        acc['lat'] = enrichment.get('lat')
        acc['lng'] = enrichment.get('lng')
        acc['mapbox_id'] = enrichment.get('mapbox_id')
    if args.get('notes') is not None:
        acc['notes'] = args['notes']

    if new_ci:
        acc['check_in_date'] = new_ci
    if new_co:
        acc['check_out_date'] = new_co

    storage.set_trip_metadata(event_id, metadata)
    if acc.get('check_in_date') and acc.get('check_out_date'):
        span = _stay_label(acc['check_in_date'], acc['check_out_date'], metadata)
    else:
        span = "no dates"
    msg = f"Updated accommodation '{acc.get('name')}' ({span})."
    if clip_notes:
        msg += " Adjusted neighboring stays to make room: " + "; ".join(clip_notes) + "."
    return {"status": "success", "message": msg}

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
        
    for field in ['name', 'category', 'duration_mins', 'priority']:
        if args.get(field) is not None:
            target_poi[field] = args.get(field)

    if args.get('location') is not None:
        # re-ground the POI: keeping the old coords/ids for a new location would
        # leave the scheduler routing to the old place
        from services.trip_planner import enrich_poi_data
        from services.trip_validation import reconcile_coords
        enrichment = enrich_poi_data(target_poi.get('name'), args['location'], metadata.get('location', ''))
        reconcile_coords(enrichment, {'name': target_poi.get('name'), 'location': args['location'],
                                      'approx_lat': args.get('approx_lat'),
                                      'approx_lng': args.get('approx_lng')})
        target_poi['location'] = enrichment.get('location') or args['location']
        target_poi['lat'] = enrichment.get('lat')
        target_poi['lng'] = enrichment.get('lng')
        target_poi['mapbox_id'] = enrichment.get('mapbox_id')

    if args.get('valid_days_of_week') is not None:
        target_poi['valid_days_of_week'] = args.get('valid_days_of_week')
            
    storage.set_trip_metadata(event_id, metadata)
    return {"status": "success", "message": f"Updated POI {target_poi['name']}."}


def _resolve_flight_dt(day, time_str, metadata, existing_iso=None):
    """Resolve a flight time to an ISO datetime string.

    Accepts a full ISO datetime in time_str, or a 1-indexed trip-day ordinal
    (day 1 = the trip's first day; 0 = the day before, for overnight outbound
    legs) paired with an 'HH:MM' time. Missing pieces fall back to the existing
    value's date/time (edits), then to 12:00. Returns (iso_or_None, error_or_None).
    """
    import datetime
    time_str = str(time_str) if time_str is not None else ''
    if 'T' in time_str:
        try:
            datetime.datetime.fromisoformat(time_str)
        except ValueError:
            return None, (f"Could not parse '{time_str}' — use 'YYYY-MM-DDTHH:MM:SS', "
                          f"or a trip-day ordinal with an 'HH:MM' time.")
        return time_str, None

    hhmm = None
    if time_str:
        try:
            hhmm = datetime.datetime.strptime(time_str, '%H:%M').strftime('%H:%M')
        except ValueError:
            return None, (f"Could not parse time '{time_str}' — use 'HH:MM' (24h) "
                          f"or a full ISO datetime.")

    date_part = None
    if day is not None:
        start_dt, _ = _trip_date_bounds(metadata)
        if not start_dt:
            return None, ("The trip has no dates yet, so trip-day ordinals can't be "
                          "resolved — give a full ISO datetime instead.")
        date_part = (start_dt.date() + datetime.timedelta(days=int(day) - 1)).strftime('%Y-%m-%d')
    elif existing_iso and 'T' in str(existing_iso):
        date_part = str(existing_iso).split('T')[0]
    if date_part is None:
        return None, ("Provide departure_day/arrival_day (1-indexed trip day) with the "
                      "'HH:MM' time, or a full ISO datetime.")
    if hhmm is None:
        if existing_iso and 'T' in str(existing_iso):
            hhmm = str(existing_iso).split('T')[1][:5]
        else:
            hhmm = '12:00'
    return f"{date_part}T{hhmm}:00", None


def _flight_time_label(iso_str, metadata):
    """Agent-facing label for a flight time. Draft trips speak in trip days —
    their mock calendar dates must never surface anywhere a user could see."""
    if not iso_str:
        return "time TBD"
    date_part, _, time_part = str(iso_str).partition('T')
    time_part = time_part[:5]
    if metadata.get('is_draft'):
        n = _night_ordinal(date_part, metadata)
        if n is not None:
            return f"day {n}" + (f" {time_part}" if time_part else "")
    return f"{date_part} {time_part}".strip()


def _validate_flight_times(dep_iso, arr_iso):
    import datetime
    if dep_iso and arr_iso:
        try:
            if datetime.datetime.fromisoformat(arr_iso) <= datetime.datetime.fromisoformat(dep_iso):
                return ("Arrival is not after departure. Remember overnight flights land the "
                        "NEXT day — set arrival_day to departure_day + 1.")
        except ValueError:
            pass
    return None


def _find_trip_flight(args, flights):
    """Locate a flight by flight_id, flight_number, or origin/destination.
    Returns (flight, error_or_None); ambiguity is an error, never a guess."""
    if args.get('flight_id'):
        f = next((x for x in flights if x.get('id') == args['flight_id']), None)
        return (f, None) if f else (None, "No flight with that flight_id on this trip.")

    def norm(s):
        return str(s or '').replace(' ', '').strip().lower()

    matches = flights
    if args.get('flight_number'):
        fn = norm(args['flight_number'])
        matches = [x for x in matches if norm(x.get('flight_number')) == fn]
    elif args.get('origin') or args.get('destination'):
        def loose(a, b):
            a, b = norm(a), norm(b)
            return bool(a) and bool(b) and (a in b or b in a)
        if args.get('origin'):
            matches = [x for x in matches if loose(args['origin'], x.get('origin'))]
        if args.get('destination'):
            matches = [x for x in matches if loose(args['destination'], x.get('destination'))]
    else:
        return None, "Provide flight_id, flight_number, or origin/destination to identify the flight."

    if not matches:
        return None, "No matching flight found on this trip."
    if len(matches) > 1:
        desc = "; ".join(f"{x.get('airline') or '?'} {x.get('flight_number') or ''} "
                         f"{x.get('origin')}->{x.get('destination')} (id {x.get('id')})"
                         for x in matches)
        return None, f"Multiple flights match: {desc}. Use flight_id."
    return matches[0], None


def handle_generate_trip_flights(args: dict) -> dict:
    from services import storage
    from models.schemas import TripMetadata
    from services.trip_planner import generate_trip_flights

    event_id = args.get('event_id')
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"status": "error", "message": f"Trip {event_id} not found."}

    trip_obj = TripMetadata(**meta)
    warning, flights = generate_trip_flights(trip_obj, args.get('prompt', ''))

    if 'flights' not in meta:
        meta['flights'] = []

    # same-route-same-day flights are re-suggestions, not additions
    def key(origin, destination, dep):
        return (str(origin or '').strip().lower(), str(destination or '').strip().lower(),
                str(dep or '').split('T')[0])
    existing_keys = {key(f.get('origin'), f.get('destination'), f.get('departure_time'))
                     for f in meta['flights']}
    added = []
    for flight in flights:
        d = flight.model_dump() if hasattr(flight, 'model_dump') else flight.dict()
        if key(d.get('origin'), d.get('destination'), d.get('departure_time')) in existing_keys:
            continue
        meta['flights'].append(d)
        added.append(d)

    storage.set_trip_metadata(event_id, meta)

    if added:
        lines = "; ".join(f"{f.get('airline') or 'TBD'} {f.get('origin')} -> {f.get('destination')} "
                          f"departing {_flight_time_label(f.get('departure_time'), meta)}"
                          for f in added)
        msg = (f"Generated and added {len(added)} flight(s) to the trip: {lines}. "
               f"These are estimates the user can correct with edit_trip_flight.")
    else:
        msg = "No new flights were added."
    res = {"status": "success", "message": msg}
    if warning:
        res["budget_warning"] = warning
    return res


def handle_add_trip_flight(args: dict) -> dict:
    from services import storage
    import uuid
    event_id = args.get('event_id')
    metadata = storage.get_trip_metadata(event_id) or {
        "event_id": event_id, "pois": [], "accommodations": [], "flights": []}

    dep_iso = arr_iso = None
    if args.get('departure_day') is not None or args.get('departure_time'):
        dep_iso, err = _resolve_flight_dt(args.get('departure_day'), args.get('departure_time'), metadata)
        if err:
            return {"status": "error", "message": err}
    if args.get('arrival_day') is not None or args.get('arrival_time'):
        arr_iso, err = _resolve_flight_dt(args.get('arrival_day'), args.get('arrival_time'), metadata)
        if err:
            return {"status": "error", "message": err}
    err = _validate_flight_times(dep_iso, arr_iso)
    if err:
        return {"status": "error", "message": err}

    flights = metadata.get('flights') or []
    dep_date = (dep_iso or '').split('T')[0]
    fn = str(args.get('flight_number') or '').replace(' ', '').lower()
    for f in flights:
        f_date = str(f.get('departure_time') or '').split('T')[0]
        same_number = fn and str(f.get('flight_number') or '').replace(' ', '').lower() == fn
        same_route = (str(f.get('origin') or '').strip().lower() == str(args.get('origin') or '').strip().lower()
                      and str(f.get('destination') or '').strip().lower() == str(args.get('destination') or '').strip().lower())
        if (same_number or (not fn and same_route)) and dep_date and f_date == dep_date:
            return {"status": "error",
                    "message": (f"That flight already exists on this trip: "
                                f"{f.get('airline') or '?'} {f.get('flight_number') or ''} "
                                f"{f.get('origin')}->{f.get('destination')} departing "
                                f"{_flight_time_label(f.get('departure_time'), metadata)} "
                                f"(id {f.get('id')}). Use edit_trip_flight to change it.")}

    flight = {
        "id": uuid.uuid4().hex,
        "airline": args.get('airline'),
        "flight_number": args.get('flight_number'),
        "origin": args.get('origin'),
        "destination": args.get('destination'),
        "departure_time": dep_iso,
        "arrival_time": arr_iso,
        "class_type": args.get('class_type'),
        "estimated_price_usd": args.get('estimated_price_usd'),
        "is_live_price": False,
        "notes": args.get('notes', ''),
    }
    if 'flights' not in metadata:
        metadata['flights'] = []
    metadata['flights'].append(flight)
    storage.set_trip_metadata(event_id, metadata)

    msg = (f"Added flight {args.get('origin')} -> {args.get('destination')} "
           f"(departs {_flight_time_label(dep_iso, metadata)}).")
    assumed = [w for w, d, t in (("departure", args.get('departure_day'), args.get('departure_time')),
                                 ("arrival", args.get('arrival_day'), args.get('arrival_time')))
               if d is not None and not t]
    if assumed:
        msg += f" Note: {' and '.join(assumed)} time assumed 12:00 — give the real time to correct it."
    return {"status": "success", "message": msg}


def handle_edit_trip_flight(args: dict) -> dict:
    from services import storage
    event_id = args.get('event_id')
    metadata = storage.get_trip_metadata(event_id)
    if not metadata or not metadata.get('flights'):
        return {"status": "error", "message": "Trip not found or has no flights."}

    f, err = _find_trip_flight(args, metadata['flights'])
    if err:
        return {"status": "error", "message": err}

    # resolve and validate time changes BEFORE mutating anything, so a rejected
    # edit leaves the flight untouched
    dep_iso = arr_iso = None
    if args.get('departure_day') is not None or args.get('departure_time'):
        dep_iso, err = _resolve_flight_dt(args.get('departure_day'), args.get('departure_time'),
                                          metadata, existing_iso=f.get('departure_time'))
        if err:
            return {"status": "error", "message": err}
    if args.get('arrival_day') is not None or args.get('arrival_time'):
        arr_iso, err = _resolve_flight_dt(args.get('arrival_day'), args.get('arrival_time'),
                                          metadata, existing_iso=f.get('arrival_time'))
        if err:
            return {"status": "error", "message": err}
    err = _validate_flight_times(dep_iso or f.get('departure_time'), arr_iso or f.get('arrival_time'))
    if err:
        return {"status": "error", "message": err}

    if args.get('airline') is not None:
        f['airline'] = args['airline']
    if args.get('class_type') is not None:
        f['class_type'] = args['class_type']
    if args.get('notes') is not None:
        f['notes'] = args['notes']
    if args.get('new_flight_number'):
        f['flight_number'] = args['new_flight_number']
    if args.get('new_origin'):
        f['origin'] = args['new_origin']
    if args.get('new_destination'):
        f['destination'] = args['new_destination']
    if args.get('estimated_price_usd') is not None:
        f['estimated_price_usd'] = args['estimated_price_usd']
        # a hand-edited price is an estimate again, not a SerpApi live quote
        f['is_live_price'] = False
    if dep_iso:
        f['departure_time'] = dep_iso
    if arr_iso:
        f['arrival_time'] = arr_iso

    storage.set_trip_metadata(event_id, metadata)
    return {"status": "success",
            "message": (f"Updated flight {f.get('origin')} -> {f.get('destination')} "
                        f"(departs {_flight_time_label(f.get('departure_time'), metadata)}).")}


def handle_delete_trip_flight(args: dict) -> dict:
    from services import storage
    event_id = args.get('event_id')
    metadata = storage.get_trip_metadata(event_id)
    if not metadata or not metadata.get('flights'):
        return {"status": "error", "message": "Trip not found or has no flights."}

    f, err = _find_trip_flight(args, metadata['flights'])
    if err:
        return {"status": "error", "message": err}

    metadata['flights'] = [x for x in metadata['flights'] if x.get('id') != f.get('id')]
    storage.set_trip_metadata(event_id, metadata)
    return {"status": "success",
            "message": (f"Deleted flight {f.get('airline') or ''} {f.get('flight_number') or ''} "
                        f"{f.get('origin')} -> {f.get('destination')}.").replace("  ", " ")}


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

def handle_get_point_balances(args: dict) -> dict:
    # Shared implementation with the v2 (Gemma router) stack so both agent
    # stacks stay in lockstep on chore-point behavior.
    from services.agent_tools_v2 import get_point_balances
    return get_point_balances()

def handle_adjust_points(args: dict) -> dict:
    from services.agent_tools_v2 import adjust_points
    return adjust_points(args.get("member_name", ""),
                         delta=args.get("delta"), set_to=args.get("set_to"),
                         note=args.get("note", ""))

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
    "add_trip_accommodation": handle_add_trip_accommodation,
    "edit_trip_accommodation": handle_edit_trip_accommodation,
    "edit_trip_poi": handle_edit_trip_poi,
    "generate_trip_flights": handle_generate_trip_flights,
    "add_trip_flight": handle_add_trip_flight,
    "edit_trip_flight": handle_edit_trip_flight,
    "delete_trip_flight": handle_delete_trip_flight,
    "get_point_balances": handle_get_point_balances,
    "adjust_points": handle_adjust_points,
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
