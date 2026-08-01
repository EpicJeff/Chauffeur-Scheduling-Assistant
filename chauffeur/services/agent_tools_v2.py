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
    from services.storage import get_cached_schedule, get_all_drivers
    import re
    from dateutil.parser import parse
    import datetime

    sched = get_cached_schedule()
    events = sched.get("events", [])
    # Join solver assignments so the model can answer "whose schedule" questions
    # — without this it sees events but no drivers and reports empty schedules.
    assignments = dict(sched.get("assignments", {}))
    assignments.update(sched.get("ghost_assignments", {}))
    driver_names = {d.get("id"): d.get("name") for d in get_all_drivers()}

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
                    drv_id = assignments.get(ev.get("id"))
                    slim_events.append({
                        "id": ev.get("id"),
                        "title": ev.get("title"),
                        "location": ev.get("location"),
                        "start": ev.get("start"),
                        "end": ev.get("end"),
                        "assigned_driver": driver_names.get(drv_id, drv_id)
                    })
            except ValueError:
                pass
        
    return {"status": "success", "events": slim_events}


def _find_event_fuzzy(event_name: str, target_date: str):
    """
    Shared fuzzy event lookup over the cached schedule.
    Returns (event, None) on a match, or (None, error_message) when nothing fits.
    """
    from services.storage import get_cached_schedule
    import datetime

    sched = get_cached_schedule()
    events = sched.get("events", [])

    # Clean and parse the target date robustly
    import re
    from dateutil.parser import parse

    target_date_clean = re.sub(r'(?i)\b(this|next|last|on|the|upcoming)\b\s+', '', target_date).strip()
    target_dt = None
    try:
        low = target_date_clean.lower()
        if low in ('today', 'tonight', 'this evening', 'evening', 'now'):
            target_dt = datetime.datetime.now()
        elif low in ('tomorrow', 'tomorrow night', 'tomorrow evening', 'tomorrow morning'):
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
        return None, f"Could not find any event containing '{event_name}' on {target_date}."
    return target_event, None


def assign_driver_to_event_fuzzy(event_name: str, driver_name: str, target_date: str) -> Dict[str, Any]:
    """
    Finds an event by name on a specific date and assigns a driver to it via a manual override.
    target_date must be YYYY-MM-DD.
    """
    from services.storage import add_override, get_all_drivers

    target_event, err = _find_event_fuzzy(event_name, target_date)
    if err:
        return {"status": "error", "message": err}

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


def remove_override_for_event_fuzzy(event_name: str, target_date: str) -> Dict[str, Any]:
    """
    Removes any manual driver override(s) for an event found by fuzzy name match
    on a date, returning the event to solver control. Covers split-leg override
    ids ({base}_dropoff / {base}_pickup) alongside the base event id.
    """
    from services.storage import delete_override_by_event, get_all_overrides

    target_event, err = _find_event_fuzzy(event_name, target_date)
    if err:
        return {"status": "error", "message": err}

    ev_id = target_event["id"]
    base = ev_id
    for suffix in ("_dropoff", "_pickup"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    candidates = {ev_id, base, f"{base}_dropoff", f"{base}_pickup"}

    existing = {o.get("event_id") for o in get_all_overrides()}
    removed = sorted(c for c in candidates if c in existing)
    for c in removed:
        delete_override_by_event(c)

    if not removed:
        return {"status": "success",
                "message": f"'{target_event['title']}' has no manual overrides — it is already solver-controlled."}

    return {"status": "success",
            "message": f"Removed the manual override for '{target_event['title']}'. The solver will now choose the driver.",
            "target_element_id": _get_target_element_id("event", ev_id),
            "ui_action": "jump_and_reload"}

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

def _find_child_member(member_name: str):
    """Fuzzy-resolve a child member by name (exact, then substring, both
    case-insensitive). Returns (member, error_message)."""
    from services import storage
    children = [m for m in storage.get_all_members() if m.get('role') == 'child']
    if not children:
        return None, "There are no child members set up yet."
    name = (member_name or '').strip().lower()
    if not name:
        return None, "Which child do you mean? Please give a name."
    exact = [m for m in children if (m.get('name') or '').lower() == name]
    if len(exact) == 1:
        return exact[0], None
    partial = [m for m in children if name in (m.get('name') or '').lower()
               or (m.get('name') or '').lower() in name]
    if len(partial) == 1:
        return partial[0], None
    names = ", ".join(m.get('name') or '?' for m in children)
    return None, f"I couldn't match '{member_name}' to one child. The children are: {names}."


def get_point_balances() -> Dict[str, Any]:
    """Chore-point balances for every child, sorted highest first."""
    from services import storage
    balances = storage.get_all_point_balances()
    if not balances:
        return {"status": "success", "balances": [],
                "message": "No children are earning points yet."}
    msg = ", ".join(f"{b['name']} has {b['balance']} points" for b in balances)
    return {"status": "success", "balances": balances, "message": msg + "."}


def adjust_points(member_name: str, delta: int = None, set_to: int = None,
                  note: str = "", by_member_id: str = None) -> Dict[str, Any]:
    """Manual point adjustment for a child, as an append-only ledger entry.
    Give either delta (relative) or set_to (absolute)."""
    from services import storage
    member, err = _find_child_member(member_name)
    if err:
        return {"status": "error", "message": err}
    if (delta is None) == (set_to is None):
        return {"status": "error",
                "message": "Give either a relative change (delta) or a target balance (set_to), not both."}
    if delta is None:
        delta = int(set_to) - storage.get_points_balance(member['id'])
    else:
        delta = int(delta)
    if delta == 0:
        balance = storage.get_points_balance(member['id'])
        return {"status": "success",
                "message": f"{member['name']} already has {balance} points — nothing to change."}
    balance = storage.adjust_points(member['id'], delta, note or '', by_member_id)
    change = f"+{delta}" if delta > 0 else str(delta)
    return {"status": "success",
            "message": f"Done — {change} points for {member['name']}. They now have {balance} points."}


# ==============================================================================
# TOOL REGISTRY (For Gemma Router)
# ==============================================================================

def manage_trip_flights(trip_id: str, action: str, prompt: str = "", flight: Dict[str, Any] = None) -> Dict[str, Any]:
    """Flight management for the v2 router. Thin wrapper over the validated v1
    handlers (generation, dedup, trip-day ordinals, draft-safe messages) so both
    agent stacks share one implementation."""
    from services import agent_tools
    action = (action or "generate").lower()
    args = {"event_id": trip_id}
    if isinstance(flight, dict):
        args.update(flight)

    if action == "generate":
        res = agent_tools.handle_generate_trip_flights({"event_id": trip_id, "prompt": prompt or ""})
    elif action == "add":
        res = agent_tools.handle_add_trip_flight(args)
    elif action == "edit":
        res = agent_tools.handle_edit_trip_flight(args)
    elif action == "delete":
        res = agent_tools.handle_delete_trip_flight(args)
    else:
        return {"status": "error",
                "message": f"Unknown flight action '{action}' — use generate, add, edit, or delete."}

    if res.get("status") == "success":
        res["ui_action"] = "sync"
    return res


def get_available_tools() -> List[Dict]:
    """
    Returns the JSON schemas for the tools available to the Gemma router.
    """
    return [
        {
            "name": "get_calendar_events",
            "description": "Retrieves calendar events for a date range, each with its assigned_driver (null = unassigned). This is the CORRECT tool for questions about a specific driver's schedule or drives: fetch the range, then filter by assigned_driver.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "The start date as YYYY-MM-DD, resolved from the CURRENT DATE in your context."},
                    "end_date": {"type": "string", "description": "The end date as YYYY-MM-DD (inclusive), resolved from the CURRENT DATE in your context."}
                },
                "required": ["start_date", "end_date"]
            }
        },
        {
            "name": "remove_override_for_event_fuzzy",
            "description": "Removes/clears any manual driver override for a specific event (found by fuzzy name match on a date), returning it to automatic solver control. This is the CORRECT tool when the user asks to remove, clear, undo, or reset an assignment or override. It does NOT assign anyone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the event or a substring of it."},
                    "target_date": {"type": "string", "description": "The date the event occurs as YYYY-MM-DD, resolved from the CURRENT DATE in your context (relative terms like 'tonight' or 'tomorrow' are also accepted)."}
                },
                "required": ["event_name", "target_date"]
            }
        },
        {
            "name": "assign_driver_to_event_fuzzy",
            "description": "Overrides the assigned driver for a specific event by finding it based on a fuzzy name match on a specific date. This is the CORRECT way to assign a driver or override an assignment. Only use it when the user names a driver to assign — to remove/undo an override use remove_override_for_event_fuzzy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the event or a substring of it."},
                    "driver_name": {"type": "string", "description": "The name or role of the driver to assign."},
                    "target_date": {"type": "string", "description": "The date the event occurs as YYYY-MM-DD, resolved from the CURRENT DATE in your context (relative terms like 'tonight' or 'tomorrow' are also accepted)."}
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
            "name": "manage_trip_flights",
            "description": ("Generate, add, edit, or delete flights on a trip. "
                            "Use action 'generate' whenever the user asks to add, suggest, or find flights "
                            "WITHOUT giving specific flight details — do NOT ask them for flight numbers, "
                            "times, or airports first: the system already knows the family's home location, "
                            "the trip destination, and the dates, and it adds realistic round-trip flights "
                            "as editable estimates. "
                            "Use 'add' only when the user provided a specific flight's details, and "
                            "'edit'/'delete' to change or remove an existing flight (match by id or route)."),
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["generate", "add", "edit", "delete"]},
                    "prompt": {"type": "string", "description": "For 'generate': the user's request verbatim, including any stated origin, airline, or cabin preferences. Empty is fine for a bare 'add flights'."},
                    "flight": {
                        "type": "object",
                        "description": ("For add/edit/delete. Fields: origin, destination (add: REQUIRED), airline, flight_number, "
                                        "class_type, estimated_price_usd (total for the whole party), notes, "
                                        "departure_day/arrival_day (1-indexed trip day; 0 = the day before the trip for overnight outbound) "
                                        "with departure_time/arrival_time as 'HH:MM' 24h — never show draft mock calendar dates to the user. "
                                        "For edit/delete matching: flight_id (preferred), or flight_number, or origin+destination. "
                                        "For edit renames use new_origin/new_destination/new_flight_number. Do NOT invent other fields.")
                    }
                },
                "required": ["trip_id", "action"]
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
        },
        {
            "name": "get_point_balances",
            "description": "Gets the current chore-point balance for every child. Use for questions like 'how many points does Bob have' or 'who is winning on points'.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "adjust_points",
            "description": "Adds, subtracts, or sets a child's chore points (a parent-level manual adjustment, recorded in the points history). Use delta for relative changes ('give Bob 20 points' -> delta 20, 'take away 5' -> delta -5) or set_to for absolute ('set Bob to 100'). Never both.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string", "description": "The child's name."},
                    "delta": {"type": "integer", "description": "Relative change, negative to subtract."},
                    "set_to": {"type": "integer", "description": "Absolute target balance."},
                    "note": {"type": "string", "description": "Short reason shown in the points history, e.g. 'Helped carry groceries'."}
                },
                "required": ["member_name"]
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

# ==============================================================================
# DRIVER TOOLS (PWA chat context — driver_id is injected server-side, never
# supplied by the LLM)
# ==============================================================================

def _leg_id_variants(event_id: str) -> List[str]:
    # The PWA constructs leg ids client-side (init_{ev}[_1|_2], route_{ev}_1..3,
    # final_{ev}); the drive_status store is keyed by those strings. Marking the
    # whole family covers every layout the timeline can render; unused ids are
    # inert rows the UI never looks up.
    return ([f"init_{event_id}", f"init_{event_id}_1", f"init_{event_id}_2"] +
            [f"route_{event_id}_{i}" for i in (1, 2, 3)] +
            [f"final_{event_id}", f"final_{event_id}_1"])


def _parse_fuzzy_date(target_date: str):
    import datetime
    import re
    from dateutil.parser import parse
    cleaned = re.sub(r'(?i)\b(this|next|last|on|the|upcoming)\b\s+', '', (target_date or 'today')).strip()
    try:
        if cleaned.lower() in ('', 'today', 'now', 'tonight'):
            return datetime.datetime.now().date()
        if cleaned.lower() == 'tomorrow':
            return (datetime.datetime.now() + datetime.timedelta(days=1)).date()
        return parse(cleaned, default=datetime.datetime.now()).date()
    except Exception:
        return datetime.datetime.now().date()


def _driver_events_for_date(driver_id: str, target_date) -> List[Dict[str, Any]]:
    """The driver's assigned events (real + ghost assignments) on a date, with
    per-event drive status derived from the drive_status store."""
    import datetime
    from services.storage import get_cached_schedule, get_completed_drives, get_in_progress_drives
    sched = get_cached_schedule()
    assignments = dict(sched.get("assignments", {}))
    assignments.update(sched.get("ghost_assignments", {}))
    completed = set(get_completed_drives())
    in_progress = set(get_in_progress_drives())

    result = []
    for ev in sched.get("events", []):
        if assignments.get(ev.get("id")) != driver_id:
            continue
        ev_start = ev.get("start", "")
        try:
            if datetime.datetime.fromisoformat(ev_start.replace('Z', '+00:00')).date() != target_date:
                continue
        except (ValueError, AttributeError):
            continue
        variants = set(_leg_id_variants(ev.get("id")))
        status = "pending"
        if variants & in_progress:
            status = "driving now"
        if variants & completed:
            status = "completed"
        result.append({
            "id": ev.get("id"),
            "title": ev.get("title"),
            "location": ev.get("location"),
            "start": ev.get("start"),
            "end": ev.get("end"),
            "drive_status": status,
        })
    result.sort(key=lambda e: e.get("start") or "")
    return result


def _fuzzy_pick_event(events: List[Dict[str, Any]], event_name: str):
    import re
    name_lower = (event_name or "").lower().strip()
    stop_words = {"to", "for", "the", "a", "at", "on", "in", "and", "my", "drive"}
    search_words = set(w for w in re.findall(r'\w+', name_lower) if w not in stop_words)
    best, best_score = None, 0
    for ev in events:
        title = (ev.get("title") or "").lower()
        if name_lower and (name_lower in title or (title in name_lower and len(title) > 3)):
            return ev
        title_words = set(w for w in re.findall(r'\w+', title) if w not in stop_words)
        overlap = len(search_words & title_words)
        if overlap > best_score:
            best, best_score = ev, overlap
    return best


def get_my_route(driver_id: str, target_date: str = "today") -> Dict[str, Any]:
    """Lists the calling driver's assigned events and drive statuses for a day."""
    from services.storage import get_all_drivers
    day = _parse_fuzzy_date(target_date)
    events = _driver_events_for_date(driver_id, day)
    d = next((d for d in get_all_drivers() if d.get("id") == driver_id), None)
    if not events:
        return {"status": "success", "message": f"No drives assigned to {d.get('name') if d else 'you'} on {day.isoformat()}.", "events": []}
    return {"status": "success", "date": day.isoformat(), "events": events}


def start_route(driver_id: str, event_name: str, target_date: str = "today") -> Dict[str, Any]:
    """Marks the drive for a fuzzy-matched event as in progress (same
    drive_status store the PWA's Start Drive button writes)."""
    from services.storage import mark_drive_status
    day = _parse_fuzzy_date(target_date)
    events = _driver_events_for_date(driver_id, day)
    if not events:
        return {"status": "error", "message": f"You have no assigned drives on {day.isoformat()}."}
    ev = _fuzzy_pick_event(events, event_name)
    if not ev:
        return {"status": "error", "message": f"Couldn't find a drive matching '{event_name}' on your schedule for {day.isoformat()}."}
    for leg_id in _leg_id_variants(ev["id"]):
        mark_drive_status(leg_id, "in_progress")
    return {"status": "success",
            "message": f"On your way to '{ev['title']}'" + (f" at {ev['location']}" if ev.get("location") else "") + ". Drive safe!",
            "event_id": ev["id"]}


def complete_route(driver_id: str, event_name: str, action: str = "completed", target_date: str = "today") -> Dict[str, Any]:
    """Marks a fuzzy-matched drive as done: records a telemetry event (same as
    the PWA's Mark Completed button) and completes the drive_status legs."""
    from services.storage import mark_drive_status, add_telemetry_event
    import time as _time
    import uuid
    day = _parse_fuzzy_date(target_date)
    events = _driver_events_for_date(driver_id, day)
    if not events:
        return {"status": "error", "message": f"You have no assigned drives on {day.isoformat()}."}
    ev = _fuzzy_pick_event(events, event_name)
    if not ev:
        return {"status": "error", "message": f"Couldn't find a drive matching '{event_name}' on your schedule for {day.isoformat()}."}
    allowed = {"picked up", "dropped off", "arrived", "completed"}
    action_str = action if action in allowed else "completed"
    add_telemetry_event({
        "id": uuid.uuid4().hex,
        "driver_id": driver_id,
        "event_id": ev["id"],
        "action": action_str,
        "timestamp": _time.time(),
        "details": f"Via chat: {action_str} for '{ev['title']}'",
    })
    for leg_id in _leg_id_variants(ev["id"]):
        mark_drive_status(leg_id, "completed")
    return {"status": "success",
            "message": f"Got it — marked '{ev['title']}' as {action_str}.",
            "event_id": ev["id"]}


def get_driver_tools() -> List[Dict]:
    """Extra tool schemas exposed only in PWA driver chat. driver_id is
    deliberately absent from the schemas — the router injects the logged-in
    driver's id when dispatching."""
    return [
        {
            "name": "get_my_route",
            "description": "Gets YOUR (the driver's) assigned drives and their statuses for a day. Use when the driver asks about their schedule, next drive, or what's left.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "e.g. 'today' (default), 'tomorrow', 'Friday'."}
                },
                "required": []
            }
        },
        {
            "name": "start_route",
            "description": "Marks one of YOUR drives as started / in progress. Use when the driver says they are leaving, heading out, or starting a drive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The event the drive is for, e.g. 'soccer practice'."},
                    "target_date": {"type": "string", "description": "Defaults to today."}
                },
                "required": ["event_name"]
            }
        },
        {
            "name": "complete_route",
            "description": "Marks one of YOUR drives as done. Use when the driver says they picked someone up, dropped someone off, arrived, or finished a drive. Choose the action that matches their words.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The event the drive is for."},
                    "action": {"type": "string", "enum": ["picked up", "dropped off", "arrived", "completed"]},
                    "target_date": {"type": "string", "description": "Defaults to today."}
                },
                "required": ["event_name"]
            }
        }
    ]
