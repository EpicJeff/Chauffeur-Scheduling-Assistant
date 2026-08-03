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


def reopen_chore(chore_title: str) -> Dict[str, Any]:
    """Puts a verified or claimed chore back in the pot (open) so it can be
    claimed again this period. Fuzzy title match; 'done' chores are refused
    toward verify/reject."""
    from services import storage
    name = (chore_title or '').strip().lower()
    if not name:
        return {"status": "error", "message": "Which chore should I reopen? Please give its name."}
    chores = storage.get_all_chores()
    matches = [c for c in chores if (c.get('title') or '').lower() == name] \
        or [c for c in chores if name in (c.get('title') or '').lower()]
    if not matches:
        return {"status": "error", "message": f"I couldn't find a chore matching '{chore_title}'."}
    reopenable = [c for c in matches if c.get('state') in ('verified', 'claimed')]
    if not reopenable:
        c = matches[0]
        if c.get('state') == 'open':
            return {"status": "success", "message": f"'{c['title']}' is already open and up for grabs."}
        return {"status": "error",
                "message": f"'{c['title']}' is finished and waiting for a parent to verify it — "
                           "verify or reject it in the app instead of reopening."}
    if len(reopenable) > 1:
        names = ", ".join(c['title'] for c in reopenable)
        return {"status": "error", "message": f"That matches more than one chore: {names}. Which one?"}
    chore = reopenable[0]
    storage.reopen_chore(chore['id'])
    # Same "chore available" fan-out the reopen endpoint sends, off-thread so
    # push latency never eats into the agent's reply budget.
    try:
        import threading
        import main as _main
        fresh = storage.get_chore(chore['id'])
        threading.Thread(target=_main._notify_chore_event, args=('posted', fresh),
                         daemon=True).start()
    except Exception:
        pass
    extra = " Points already earned from it stay." if chore.get('state') == 'verified' else ""
    return {"status": "success",
            "message": f"Done — '{chore['title']}' is back in the pot and up for grabs.{extra}"}


# ==============================================================================
# TOOL REGISTRY (For Gemma Router)
# ==============================================================================

# --- Family hub tools (messaging / chores / routines) ------------------------
# Shared implementations for BOTH agent stacks. Identity rules: in PWA driver
# chat the logged-in driver's member is the trusted actor (sender_driver_id,
# injected server-side, never taken from the LLM); in admin/voice contexts the
# speaker must name themselves (from_member / member_name) or the tool asks.

def _member_for_driver(driver_id: str):
    if not driver_id:
        return None
    from services.storage import get_all_members
    return next((m for m in get_all_members() if m.get('driver_id') == driver_id), None)


def _find_member_fuzzy(name: str):
    if not name:
        return None
    from services.storage import get_all_members
    target = name.strip().lower()
    members = get_all_members()
    exact = [m for m in members if (m.get('name') or '').strip().lower() == target]
    if len(exact) == 1:
        return exact[0]
    sub = [m for m in members if target and target in (m.get('name') or '').strip().lower()]
    return sub[0] if len(sub) == 1 else None


def _member_names() -> str:
    from services.storage import get_all_members
    return ', '.join(m.get('name') for m in get_all_members()
                     if m.get('name') and not m.get('system'))


def _resolve_actor(sender_driver_id: str = None, member_name: str = None):
    """Returns (member, None) or (None, error_result)."""
    m = _member_for_driver(sender_driver_id)
    if m:
        return m, None
    if member_name:
        m = _find_member_fuzzy(member_name)
        if m:
            return m, None
        return None, {"status": "error",
                      "message": f"I couldn't find a family member named '{member_name}'. Family members: {_member_names()}."}
    return None, {"status": "error",
                  "message": "I need to know who this is from — tell me your name (for example: \"this is Mom\")."}


def _post_chat_message(channel: dict, sender: dict, body: str, card: dict = None) -> dict:
    """Store a chat message and fire the same SSE + push fan-out as the
    /api/channels POST endpoint. main is lazily imported (it is the running
    app module); in tests it is absent and fan-out is skipped silently.
    An optional card renders as an interactive element (e.g. an action proposal)."""
    from models.schemas import ChatMessage
    from services import storage
    message = ChatMessage(channel_id=channel['id'], sender_member_id=sender['id'],
                          body=body, card=card).model_dump()
    storage.add_chat_message(message)
    storage.set_last_read(channel['id'], sender['id'], message['ts'])
    try:
        import main as _main
        recipients = channel.get('member_ids') if channel.get('kind') in ('dm', 'group') else None
        _main._push_message_event(channel['id'], recipients)
        import threading
        threading.Thread(target=_main._fanout_message_notifications,
                         args=(channel, message), daemon=True).start()
    except Exception as e:
        print(f"Agent message fan-out skipped: {e}")
    return message


def send_family_message(message_text: str, sender_driver_id: str = None,
                        from_member: str = None) -> Dict[str, Any]:
    from services import storage
    text = (message_text or '').strip()
    if not text:
        return {"status": "error", "message": "There's no message text to send."}
    sender, err = _resolve_actor(sender_driver_id, from_member)
    if err:
        return err
    if sender.get('role') == 'helper':
        return {"status": "error", "message": "Helpers can only send direct messages to parents."}
    storage.ensure_family_channel()
    channel = storage.get_family_channel()
    if not channel:
        return {"status": "error", "message": "The family channel isn't set up yet."}
    _post_chat_message(channel, sender, text)
    return {"status": "success",
            "message": f"Sent to the family channel from {sender.get('name')}: “{text}”"}


def send_direct_message(recipient_name: str, message_text: str,
                        sender_driver_id: str = None, from_member: str = None) -> Dict[str, Any]:
    from services import storage
    text = (message_text or '').strip()
    if not text:
        return {"status": "error", "message": "There's no message text to send."}
    sender, err = _resolve_actor(sender_driver_id, from_member)
    if err:
        return err
    recipient = _find_member_fuzzy(recipient_name)
    if not recipient:
        return {"status": "error",
                "message": f"I couldn't find '{recipient_name}'. Family members: {_member_names()}."}
    if recipient['id'] == sender['id']:
        return {"status": "error", "message": "That message would go to yourself."}
    # Same helper rules the messaging endpoint enforces.
    if sender.get('role') == 'helper' and recipient.get('role') != 'parent':
        return {"status": "error", "message": "Helpers can only send direct messages to parents."}
    if recipient.get('role') == 'helper' and sender.get('role') != 'parent':
        return {"status": "error",
                "message": "Only parents can message helpers directly — post in the family channel instead."}
    dm = storage.get_or_create_dm(sender['id'], recipient['id'])
    _post_chat_message(dm, sender, text)
    return {"status": "success",
            "message": f"Sent to {recipient.get('name')} from {sender.get('name')}: “{text}”"}


def get_family_messages(limit: int = 10, requester_driver_id: str = None) -> Dict[str, Any]:
    import datetime
    from services import storage
    requester = _member_for_driver(requester_driver_id)
    if requester and requester.get('role') == 'helper':
        return {"status": "error", "message": "Helpers don't have access to the family channel."}
    channel = storage.get_family_channel()
    msgs = storage.get_channel_messages(channel['id'], limit=max(1, min(int(limit or 10), 25))) if channel else []
    if not msgs:
        return {"status": "success", "message": "No family messages yet."}
    names = {m['id']: m.get('name', '?') for m in storage.get_all_members()}
    lines = []
    for m in msgs:
        t = datetime.datetime.fromtimestamp(m.get('ts', 0)).strftime('%a %I:%M %p').lstrip('0')
        lines.append(f"{names.get(m.get('sender_member_id'), 'Unknown')} ({t}): {m.get('body', '')}")
    return {"status": "success", "message": "Recent family messages:\n" + "\n".join(lines)}


def list_chores() -> Dict[str, Any]:
    from services import storage
    chores = storage.get_all_chores()
    names = {m['id']: m.get('name', '?') for m in storage.get_all_members()}
    open_c = [c for c in chores if c.get('state') == 'open']
    claimed = [c for c in chores if c.get('state') == 'claimed']
    done = [c for c in chores if c.get('state') == 'done']
    parts = []
    if open_c:
        parts.append("Open (up for grabs): " + "; ".join(
            f"{c.get('title')} ({c.get('points', 0)} pts)" for c in open_c))
    if claimed:
        parts.append("Claimed: " + "; ".join(
            f"{c.get('title')} — {names.get(c.get('claimed_by'), '?')}" for c in claimed))
    if done:
        parts.append("Waiting for a parent to verify: " + "; ".join(
            f"{c.get('title')} — {names.get(c.get('claimed_by'), '?')}" for c in done))
    if not parts:
        return {"status": "success", "message": "The chore pot is empty right now."}
    return {"status": "success", "message": " | ".join(parts)}


def claim_chore(chore_title: str, member_name: str = None,
                sender_driver_id: str = None) -> Dict[str, Any]:
    from services import storage
    actor, err = _resolve_actor(sender_driver_id, member_name)
    if err:
        # Claiming needs an actor: reword the ask for this tool.
        if not member_name:
            err = dict(err, message="Who is claiming it? Tell me the family member's name.")
        return err
    if actor.get('role') == 'helper':
        return {"status": "error", "message": "Helpers can't claim family chores."}
    title = (chore_title or '').strip().lower()
    if not title:
        return {"status": "error", "message": "Which chore should be claimed?"}
    chores = storage.get_all_chores()
    matches = [c for c in chores if title in (c.get('title') or '').lower()]
    open_matches = [c for c in matches if c.get('state') == 'open']
    if not matches:
        return {"status": "error", "message": f"No chore matches '{chore_title}'."}
    if not open_matches:
        c = matches[0]
        return {"status": "error",
                "message": f"'{c.get('title')}' isn't open right now (state: {c.get('state')})."}
    chore = open_matches[0]
    # Per-chore eligibility list (empty = any non-helper member).
    eligible = chore.get('eligible_member_ids') or []
    if eligible and actor['id'] not in eligible:
        return {"status": "error",
                "message": f"{actor.get('name')} isn't on the eligible list for '{chore.get('title')}'."}
    result = storage.claim_chore(chore['id'], actor['id'])
    if result == 'ok':
        pts = chore.get('points', 0)
        return {"status": "success",
                "message": f"{actor.get('name')} claimed '{chore.get('title')}'"
                           + (f" ({pts} pts on verification)." if pts else ".")}
    if result == 'cap':
        return {"status": "error",
                "message": f"{actor.get('name')} already has the maximum number of claimed chores."}
    return {"status": "error", "message": f"Couldn't claim '{chore.get('title')}' ({result})."}


def get_routine_status(member_name: str, target_date: str = "today") -> Dict[str, Any]:
    from services import storage
    member = _find_member_fuzzy(member_name)
    if not member:
        return {"status": "error",
                "message": f"I couldn't find '{member_name}'. Family members: {_member_names()}."}
    date_str = _parse_fuzzy_date(target_date).isoformat()
    items = storage.routines_for_day(member['id'], date_str)
    if not items:
        return {"status": "success",
                "message": f"{member.get('name')} has no routine items scheduled for {date_str}."}
    done = [i for i in items if i.get('checked')]
    missing = [i.get('title') for i in items if not i.get('checked')]
    streak = storage.compute_streak(member['id'])
    msg = f"{member.get('name')}'s routine for {date_str}: {len(done)}/{len(items)} done"
    if missing:
        msg += f" — still to do: {', '.join(missing)}"
    else:
        msg += " — all done! 🎉"
    if streak.get('current'):
        msg += f" 🔥 {streak['current']}-day streak."
    return {"status": "success", "message": msg}


def get_family_goals() -> Dict[str, Any]:
    """Pooled ('family goal') rewards with pledge progress."""
    from services import storage
    goals = [r for r in storage.get_rewards() if r.get('pooled')]
    if not goals:
        return {"status": "success", "goals": [],
                "message": "There are no family goals set up right now."}
    parts = []
    enriched = []
    for g in goals:
        pool = storage.get_pool_status(g)
        enriched.append({**g, 'pool': pool})
        if pool['funded']:
            parts.append(f"{g['title']} is fully funded ({pool['cost']} pts) — "
                         "waiting for a parent to grant it")
        else:
            split = ", ".join(f"{c['member_name']} {c['amount']}"
                              for c in pool['contributions']) or "no pledges yet"
            parts.append(f"{g['title']}: {pool['pledged']}/{pool['cost']} pts "
                         f"({split}; {pool['remaining']} to go)")
    return {"status": "success", "goals": enriched,
            "message": "Family goals — " + " | ".join(parts) + "."}


def contribute_to_family_goal(reward_title: str, amount: int, member_name: str = None,
                              sender_driver_id: str = None) -> Dict[str, Any]:
    """Pledge a child's points toward a pooled reward. Same hold semantics
    as the /contribute endpoint, and fires the same notification fan-out."""
    from services import storage
    actor, err = _resolve_actor(sender_driver_id, member_name)
    if err:
        if not member_name:
            err = dict(err, message="Who is chipping in? Tell me the child's name.")
        return err
    if actor.get('role') != 'child':
        return {"status": "error",
                "message": f"Only children pledge points — {actor.get('name')} isn't a child. "
                           "Parents can adjust the goal or grant it in the app."}
    title = (reward_title or '').strip().lower()
    goals = [r for r in storage.get_rewards() if r.get('pooled')]
    matches = [g for g in goals if (g.get('title') or '').lower() == title] \
        or [g for g in goals if title and title in (g.get('title') or '').lower()]
    if not matches:
        names = ", ".join(g['title'] for g in goals) or "none set up yet"
        return {"status": "error",
                "message": f"I couldn't find a family goal matching '{reward_title}'. Goals: {names}."}
    if len(matches) > 1:
        return {"status": "error",
                "message": "That matches more than one goal: "
                           + ", ".join(g['title'] for g in matches) + ". Which one?"}
    goal = matches[0]
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return {"status": "error", "message": "How many points should be pledged?"}
    result, pledged = storage.contribute_to_pool(goal['id'], actor['id'], amount)
    if result == 'full':
        return {"status": "error", "message": f"'{goal['title']}' is already fully funded."}
    if result == 'insufficient':
        spendable = storage.get_spendable_points(actor['id'])
        return {"status": "error",
                "message": f"{actor.get('name')} only has {spendable} spendable points "
                           "(pending requests and pledges count)."}
    if result != 'ok':
        return {"status": "error", "message": f"Couldn't pledge to '{goal['title']}' ({result})."}
    # Same fan-out the endpoint sends, off-thread (see reopen_chore).
    try:
        import threading
        import main as _main
        threading.Thread(target=_main._notify_pool_contribution,
                         args=(goal, actor, pledged), daemon=True).start()
    except Exception:
        pass
    pool = storage.get_pool_status(goal)
    msg = f"{actor.get('name')} pledged {pledged} points toward '{goal['title']}' — {pool['pledged']}/{pool['cost']}."
    if pledged < amount:
        msg += f" (Only {pledged} was needed to fill it.)"
    if pool['funded']:
        msg += " It's fully funded — a parent can grant it now! 🎉"
    return {"status": "success", "message": msg}


def post_weekly_digest_now(acting_member: dict = None) -> Dict[str, Any]:
    """On-demand '📊 Family Week in Review' post to the family chat — same
    builder the weekly schedule uses (services/family_digest). Children and
    helpers can't fire it (a re-postable broadcast is a parent/adult lever);
    legacy contexts with no acting member (dashboard chat, HA voice) are
    trusted admin surfaces, same as the rest of the open-admin toolset."""
    if acting_member and acting_member.get('role') in ('child', 'helper'):
        return {"status": "error",
                "message": "Only parents and adults can send the weekly digest."}
    from services import family_digest
    if family_digest.post_weekly_digest():
        return {"status": "success",
                "message": "Posted the 📊 Family Week in Review to the family chat."}
    return {"status": "success",
            "message": "There's nothing to report for this week yet, so I skipped the digest."}


def get_tomorrow_digest(member_name: str = "", driver_id: str = None) -> Dict[str, Any]:
    """READ-ONLY answer showing tomorrow's drive digest — the same content the
    evening Argyle DM sends, via the shared family_digest.build_tomorrow_digests
    builder. Never posts to any channel (the crossed-wire bug this fixes: with
    only post_weekly_digest available, 'show me the tomorrow digest' broadcast
    the weekly recap into the family chat). Driver context passes the logged-in
    driver_id for their own digest; admin/family contexts may name a member,
    else every driver's drives are summarized."""
    from services import family_digest, storage
    digest = family_digest.build_tomorrow_digests()
    drivers = digest.get("drivers") or {}
    weather = digest.get("weather")

    if member_name and not driver_id:
        low = member_name.strip().lower()
        target = next((m for m in storage.get_all_members()
                       if not m.get("system")
                       and (low == (m.get("name") or "").lower()
                            or low in (m.get("name") or "").lower())), None)
        if not target:
            return {"status": "error",
                    "message": f"I couldn't find a family member named '{member_name}'."}
        if not target.get("driver_id"):
            return {"status": "success",
                    "message": f"{target.get('name')} isn't a driver, so there's no"
                               f" drive digest for them. Try their My Day view instead."}
        driver_id = target["driver_id"]

    if driver_id:
        name = family_digest._driver_name(driver_id)
        d = drivers.get(driver_id)
        if not d:
            return {"status": "success",
                    "message": f"{name} has no drives scheduled tomorrow."}
        parts = [f"🚗 Tomorrow for {name} ({d['count']}):"]
        if weather:
            parts.append(weather)
        parts.extend(d["lines"])
        return {"status": "success", "message": "\n".join(parts)}

    if not drivers:
        return {"status": "success", "message": "No drives are scheduled for tomorrow yet."}
    parts = ["🚗 Tomorrow's drives:"]
    if weather:
        parts.append(weather)
    for d_id, d in drivers.items():
        parts.append(f"\n{family_digest._driver_name(d_id)} ({d['count']}):")
        parts.extend(d["lines"])
    return {"status": "success", "message": "\n".join(parts)}


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


def propose_family_action(action_type: str, summary: str, payload: dict = None,
                          created_by_member_id: str = None) -> Dict[str, Any]:
    """Create a schedule-changing action proposal to be confirmed in chat. The
    result carries a `card` the router surfaces onto Argyle's reply message."""
    from services import chat_actions
    return chat_actions.create_action_proposal(action_type, summary, payload or {},
                                               created_by_member_id=created_by_member_id)


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
            "name": "reopen_chore",
            "description": "Puts a chore back in the pot (open, claimable now). Use when a verified chore needs doing again this period ('put the trash chore back up') or to release a chore someone claimed but isn't doing. Chores finished and awaiting verification cannot be reopened — those get verified or rejected in the app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chore_title": {"type": "string", "description": "The chore's name (fuzzy matched)."}
                },
                "required": ["chore_title"]
            }
        },
        {
            "name": "get_point_balances",
            "description": "Gets the current chore-point balance for every child. Use for questions like 'how many points does Bob have' or 'who is winning on points'.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "get_family_goals",
            "description": "Lists the pooled 'family goal' rewards (like Family Movie Night) with how many points each child has pledged and how much is left to fund ('how close are we to movie night?', 'what family goals are there?').",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "contribute_to_family_goal",
            "description": "Pledges some of a child's points toward a pooled family-goal reward ('put 30 of my points toward movie night', 'Ben chips in 50 for eating out'). Pledged points are held, not spent — a parent grants the goal once it's fully funded. In driver chat the logged-in child pledges; otherwise member_name is required (ask who is pledging if unknown).",
            "parameters": {
                "type": "object",
                "properties": {
                    "reward_title": {"type": "string", "description": "The family goal's name (fuzzy matched)."},
                    "amount": {"type": "integer", "description": "How many points to pledge."},
                    "member_name": {"type": "string", "description": "Which child is pledging. Omit in driver chat."}
                },
                "required": ["reward_title", "amount"]
            }
        },
        {
            "name": "send_family_message",
            "description": "Posts a message to the family chat channel that everyone sees ('tell everyone dinner is at 6'). The sender must be known: in driver chat it is the logged-in member automatically; otherwise pass from_member with the speaker's name, and if you don't know who is speaking, ASK before sending.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_text": {"type": "string", "description": "The message to post, in the sender's voice."},
                    "from_member": {"type": "string", "description": "Who the message is from (family member name). Omit in driver chat — the sender is already known."}
                },
                "required": ["message_text"]
            }
        },
        {
            "name": "send_direct_message",
            "description": "Sends a private direct message to one family member ('tell Mom I'll be late'). Sender rules are the same as send_family_message: known automatically in driver chat, otherwise from_member is required (ask if unknown).",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_name": {"type": "string", "description": "The family member to message (fuzzy matched by name)."},
                    "message_text": {"type": "string", "description": "The message to send, in the sender's voice."},
                    "from_member": {"type": "string", "description": "Who the message is from. Omit in driver chat."}
                },
                "required": ["recipient_name", "message_text"]
            }
        },
        {
            "name": "get_family_messages",
            "description": "Reads the most recent messages from the family chat channel ('any new family messages?', 'what did I miss?').",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "How many recent messages to read (default 10, max 25)."}
                },
                "required": []
            }
        },
        {
            "name": "list_chores",
            "description": "Lists the family chore pot: what's open to claim, who has claimed what, and what's waiting for parent verification ('what chores are open?', 'who's doing the dishes?').",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "claim_chore",
            "description": "Claims an open chore for a family member ('claim the trash', 'Ben will take the dishes'). In driver chat the logged-in member claims it; otherwise member_name is required (ask who is claiming if unknown).",
            "parameters": {
                "type": "object",
                "properties": {
                    "chore_title": {"type": "string", "description": "The chore's name (fuzzy matched)."},
                    "member_name": {"type": "string", "description": "Who is claiming it. Omit in driver chat."}
                },
                "required": ["chore_title"]
            }
        },
        {
            "name": "get_routine_status",
            "description": "Checks a family member's daily routine progress and streak ('did Ben finish his routine?', 'what's left on Lily's checklist?').",
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string", "description": "Whose routine to check."},
                    "target_date": {"type": "string", "description": "Day to check, default 'today' (YYYY-MM-DD or 'yesterday')."}
                },
                "required": ["member_name"]
            }
        },
        {
            "name": "post_weekly_digest",
            "description": "Posts the 📊 'Family Week in Review' WEEKLY stats digest (driving per driver, kid activities, chores, rewards, routine streaks) into the family chat RIGHT NOW ('send the weekly digest', 'post the week in review again'). It also goes out automatically on its weekly schedule — this is the on-demand resend. NOT for tomorrow's schedule: 'tomorrow digest' / 'what does tomorrow look like' is get_tomorrow_digest, which never posts anything.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "get_tomorrow_digest",
            "description": "Shows TOMORROW's drive digest as a read-only answer — the same preview Argyle DMs each driver in the evening: drives sorted by time with prep-kit items, plus the weather line ('show me the tomorrow digest', 'what does tomorrow look like', 'what are Dad's drives tomorrow'). Posts nothing anywhere. Pass member_name for one person's drives; omit it for every driver.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string", "description": "Limit to one family member's drives; omit for all drivers."}
                },
                "required": []
            }
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
        },
        {
            "name": "propose_family_action",
            "description": "Propose a schedule- or calendar-CHANGING action for a parent to approve with one tap in the chat, instead of doing it silently. Use this in the family chat whenever the request would reassign or clear a driver, add/remove a routing or priority rule (e.g. mark a driver unavailable), add/update/remove an errand, or add a calendar event. Do NOT use it for questions, reading the schedule, sending messages, or chore claims — handle those directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string",
                                    "enum": ["reassign_driver", "clear_assignment", "add_routing_rule", "delete_routing_rule", "add_priority_rule", "delete_priority_rule", "add_errand", "update_errand", "delete_errand", "add_errand_rule", "create_event"],
                                    "description": "Which action to propose."},
                    "summary": {"type": "string", "description": "One short human sentence describing the change, shown on the card, e.g. \"Reassign Emma's 3pm pickup to Mom\", \"Mark Dad unavailable Thursday afternoon\", or \"Add Soccer practice Thu 4-5pm\"."},
                    "payload": {"type": "object", "description": "Arguments matching that action's own tool: reassign_driver -> {event_name, driver_name, target_date}; clear_assignment -> {event_name, target_date}; add_routing_rule -> {constraint_type, driver_id, ...}; add_errand -> {title, duration_mins, location, ...}; create_event -> {title, start (ISO 8601), end (ISO 8601), location?, all_day?}."}
                },
                "required": ["action_type", "summary", "payload"]
            }
        }
    ]

# ---------------------------------------------------------------------------
# v1 tool bridge — full-parity access to the scheduling-core, errand, memory,
# places, and deep trip-planning tools that were never natively ported to v2.
# Schemas come straight from v1's Pydantic models (single source of truth via
# agent_tools.get_openai_tools); execution delegates to agent_tools.execute_tool
# in the router. Admin context only — these are NEVER added to the PWA driver
# toolset, since a driver on the go must not reconfigure global scheduling.
# ---------------------------------------------------------------------------
BRIDGED_V1_TOOLS = [
    "get_current_state",
    "add_routing_rule", "delete_routing_rule",
    "add_priority_rule", "delete_priority_rule",
    "run_solver",
    "add_errand", "update_errand", "delete_errand", "get_errands",
    "add_errand_rule", "delete_errand_rule",
    "update_memory", "search_places",
    "generate_trip_plan",
    "add_trip_accommodation", "edit_trip_accommodation", "edit_trip_poi",
]

# Subset whose success means the driver schedule changed and the client must
# re-solve — the router sets schedule_dirty for these, mirroring the override
# tools. Reads (get_current_state, get_errands) and non-schedule writes
# (update_memory, search_places, trip-planning) are excluded.
SCHEDULE_MUTATING_V1_TOOLS = {
    "add_routing_rule", "delete_routing_rule",
    "add_priority_rule", "delete_priority_rule",
    "run_solver",
    "add_errand", "update_errand", "delete_errand",
    "add_errand_rule", "delete_errand_rule",
}


def get_bridged_v1_tools() -> List[Dict]:
    """v1 tool schemas reshaped into v2's flat {name, description, parameters}
    format for the admin (non-driver) toolset. Pulled live from v1's
    get_openai_tools() so the Pydantic models stay the single source of truth."""
    from services import agent_tools
    by_name = {t["function"]["name"]: t["function"] for t in agent_tools.get_openai_tools()}
    bridged = []
    for name in BRIDGED_V1_TOOLS:
        fn = by_name.get(name)
        if not fn:
            continue
        bridged.append({
            "name": name,
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return bridged


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
