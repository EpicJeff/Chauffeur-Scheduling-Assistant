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
    # include_system: Argyle sends messages, so its own name has to resolve.
    names = {m['id']: m.get('name', '?')
             for m in storage.get_all_members(include_system=True)}
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


# --- Household status (Presence & Status arc P1) ---
# docs/presence_status_design.md — "today is a chemo day" / "clear tomorrow's
# rest day" as one utterance. Setting announces (kids get the family's own
# authored words; adults get logistics); protocols themselves are authored in
# Config -> People, never by the agent (principle: the family's words, not
# generated copy).

def set_household_status(protocol_name: str, target_date: str = "today",
                         note: str = "", clear: bool = False,
                         end_date: str = "", acting_member: dict = None) -> Dict[str, Any]:
    from services import storage, status_protocols
    if acting_member and acting_member.get('role') in ('child', 'helper'):
        return {"status": "error",
                "message": "Only parents and adults can set the family status."}
    protocols = [p for p in storage.get_all_status_protocols()
                 if p.get('enabled', True)]
    if not protocols:
        return {"status": "error",
                "message": "No status day types are set up yet — a parent can "
                           "create them in Config → People → Status Days."}
    low = (protocol_name or '').strip().lower()
    hits = [p for p in protocols if low == (p.get('name') or '').lower()] \
        or [p for p in protocols if low and low in (p.get('name') or '').lower()]
    if len(hits) != 1:
        names = ", ".join(p.get('name') or '?' for p in protocols)
        return {"status": "error",
                "message": f"Which status day? The family's day types are: {names}."}
    proto = hits[0]
    day = _parse_fuzzy_date(target_date or "today")
    when = day.strftime('%A, %b') + f" {day.day}"

    if clear:
        existing = next((d for d in storage.get_status_days(
            start=day.isoformat(), end=day.isoformat())
            if d.get('protocol_id') == proto['id']), None)
        if not existing:
            return {"status": "success",
                    "message": f"{proto.get('name')} wasn't set for {when} — nothing to clear."}
        row = storage.delete_status_day(existing['id'])
        if row:
            status_protocols.announce_cleared(row)
        return {"status": "success",
                "message": f"Cleared {proto.get('emoji')} {proto.get('name')} for {when} "
                           f"and let everyone know the plans changed."}

    span_end = None
    if (end_date or '').strip():
        end_day = _parse_fuzzy_date(end_date)
        if end_day < day:
            return {"status": "error",
                    "message": f"That span ends ({end_day.strftime('%A')}) before it "
                               f"starts ({day.strftime('%A')}) — check the dates."}
        if end_day > day:
            span_end = end_day.isoformat()
            when = f"{when} through {end_day.strftime('%A, %b')} {end_day.day}"
    day_id = storage.add_status_day({
        'date': day.isoformat(), 'protocol_id': proto['id'],
        'end_date': span_end, 'note': (note or '').strip(),
        'set_by': (acting_member or {}).get('id')})
    status_protocols.announce_set(day_id)
    return {"status": "success",
            "message": f"Set {proto.get('emoji')} {proto.get('name')} for {when}. "
                       f"The kids will hear it in your words, and it leads their "
                       f"digest and My Day."}


def get_household_status(target_date: str = "today",
                         acting_member: dict = None) -> Dict[str, Any]:
    from services import status_protocols
    day = _parse_fuzzy_date(target_date or "today")
    when = day.strftime('%A, %b') + f" {day.day}"
    statuses = status_protocols.active_statuses(day.isoformat())
    if not statuses:
        return {"status": "success", "message": f"No family status is set for {when} — a normal day."}
    parts = [f"Family status for {when}:"]
    for s in statuses:
        line = f"{s['emoji']} {s['name']}"
        if s.get('member_name'):
            line += f" ({s['member_name']})"
        line += f" — {s['need_label'].lower()}"
        if s.get('note'):
            line += f". {s['note']}"
        parts.append(line)
    return {"status": "success", "message": "\n".join(parts)}


def get_drive_digest(target_date: str = "today", member_name: str = "",
                     driver_id: str = None) -> Dict[str, Any]:
    """READ-ONLY answer showing the drive digest for ANY day ('today' default,
    'tomorrow', a weekday, YYYY-MM-DD) — the same content the evening Argyle
    DM sends for tomorrow, via the shared family_digest.build_drive_digests
    builder. Never posts to any channel. History: v2.32.1 shipped this as a
    tomorrow-only tool (fixing 'tomorrow digest' broadcasting the weekly
    recap); that immediately crossed the NEXT wire — 'today's digest' matched
    the tomorrow tool — so v2.32.2 generalized it over _parse_fuzzy_date.
    Driver context passes the logged-in driver_id for their own digest;
    admin/family contexts may name a member, else all drivers summarize."""
    from services import family_digest, storage
    day = _parse_fuzzy_date(target_date or "today")
    digest = family_digest.build_drive_digests(day)
    drivers = digest.get("drivers") or {}
    weather = digest.get("weather")
    label = digest.get("label") or day.isoformat()
    when = label.lower() if label in ("Today", "Tomorrow") else f"on {label}"

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
                    "message": f"{name} has no drives scheduled {when}."}
        parts = [f"🚗 {label} for {name} ({d['count']}):"]
        if weather:
            parts.append(weather)
        parts.extend(d["lines"])
        return {"status": "success", "message": "\n".join(parts)}

    if not drivers:
        return {"status": "success", "message": f"No drives are scheduled {when}."}
    parts = [f"🚗 Drives {when}:"]
    if weather:
        parts.append(weather)
    for d_id, d in drivers.items():
        parts.append(f"\n{family_digest._driver_name(d_id)} ({d['count']}):")
        parts.extend(d["lines"])
    return {"status": "success", "message": "\n".join(parts)}


# --- Kid tasks (school/deadline list, kid-support arc K4a) ---
# Kids manage their OWN list directly (their list = their agency; no
# approval friction); parents manage any kid's; helpers refused.

_TASK_KINDS = ('homework', 'test', 'project', 'bring', 'other')


def _resolve_task_child(member_name: str, acting_member: dict = None):
    """(child_member, error_message). Kids act only on their own list."""
    from services import storage
    if acting_member and acting_member.get('role') == 'helper':
        return None, "Helpers can't manage the kids' school lists."
    if acting_member and acting_member.get('role') == 'child':
        low = (member_name or '').strip().lower()
        own = (acting_member.get('name') or '').lower()
        if low and low != own and low not in own:
            return None, (f"You can manage your own list — ask a parent to "
                          f"change {member_name}'s.")
        return acting_member, None
    children = [m for m in storage.get_all_members()
                if m.get('role') == 'child' and not m.get('system')]
    if not children:
        return None, "There are no child members set up yet."
    low = (member_name or '').strip().lower()
    if not low:
        if len(children) == 1:
            return children[0], None
        return None, ("Whose list? The children are: "
                      + ", ".join(c.get('name') or '?' for c in children))
    hits = [c for c in children
            if low == (c.get('name') or '').lower() or low in (c.get('name') or '').lower()]
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, f"I couldn't find a child named '{member_name}'."
    return None, "Which one? " + ", ".join(c.get('name') or '?' for c in hits)


def get_kid_tasks(member_name: str = "", acting_member: dict = None) -> Dict[str, Any]:
    """READ: a child's open school tasks (or every child's, for parents)."""
    import datetime as _dt
    from services import storage
    if acting_member and acting_member.get('role') == 'helper':
        return {"status": "error", "message": "Helpers can't view the kids' school lists."}
    today = _dt.date.today()

    def _lines(member):
        import main as _m
        return [_m._task_line(t, today) for t in storage.get_kid_tasks(member['id'])]

    if acting_member and acting_member.get('role') == 'child':
        lines = _lines(acting_member)
        if not lines:
            return {"status": "success", "message": "Your list is clear — nothing due! 🎉"}
        return {"status": "success", "message": "Here's your list:\n" + "\n".join(lines)}

    if member_name:
        child, err = _resolve_task_child(member_name, acting_member)
        if err:
            return {"status": "error", "message": err}
        lines = _lines(child)
        name = child.get('name')
        if not lines:
            return {"status": "success", "message": f"{name}'s list is clear — nothing due! 🎉"}
        return {"status": "success", "message": f"{name}'s list:\n" + "\n".join(lines)}

    blocks = []
    for c in storage.get_all_members():
        if c.get('role') != 'child' or c.get('system'):
            continue
        lines = _lines(c)
        if lines:
            blocks.append(f"{c.get('name')}:\n" + "\n".join(lines))
    if not blocks:
        return {"status": "success", "message": "All the kids' lists are clear! 🎉"}
    return {"status": "success", "message": "\n\n".join(blocks)}


def add_kid_task(title: str, due_date: str, member_name: str = "",
                 kind: str = "other", acting_member: dict = None) -> Dict[str, Any]:
    """Add a task to a kid's school list. Direct action, never a proposal —
    it's the kid's own list (or a parent managing it)."""
    from services import storage
    from models.schemas import KidTask
    if not (title or '').strip():
        return {"status": "error", "message": "What should the task say?"}
    child, err = _resolve_task_child(member_name, acting_member)
    if err:
        return {"status": "error", "message": err}
    day = _parse_fuzzy_date(due_date or 'tomorrow')
    kind = kind if kind in _TASK_KINDS else 'other'
    task = KidTask(member_id=child['id'], title=title.strip(), due_date=day.isoformat(),
                   kind=kind, source='agent',
                   created_by_member_id=(acting_member or {}).get('id')).model_dump()
    storage.add_kid_task(task)
    import main as _m
    emoji = _m._TASK_EMOJI.get(kind, '📌')
    whose = "your" if acting_member and acting_member.get('role') == 'child' \
        else f"{child.get('name')}'s"
    return {"status": "success",
            "message": f"Added to {whose} list: {emoji} {title.strip()} — "
                       f"due {day.strftime('%A, %b')} {day.day}."}


def complete_kid_task(task_title: str, member_name: str = "",
                      acting_member: dict = None) -> Dict[str, Any]:
    """Check a task off a kid's list (fuzzy title match on open tasks)."""
    from services import storage
    child, err = _resolve_task_child(member_name, acting_member)
    if err:
        return {"status": "error", "message": err}
    tasks = storage.get_kid_tasks(child['id'])
    if not tasks:
        return {"status": "success", "message": "The list is already clear! 🎉"}
    low = (task_title or '').strip().lower()
    hits = [t for t in tasks if low == (t.get('title') or '').lower()] \
        or [t for t in tasks if low and low in (t.get('title') or '').lower()]
    if not hits:
        return {"status": "error",
                "message": f"I couldn't find '{task_title}' on the list. Open: "
                           + ", ".join(t.get('title') or '?' for t in tasks[:6])}
    if len(hits) > 1:
        return {"status": "error",
                "message": "Which one? " + ", ".join(t.get('title') or '?' for t in hits)}
    storage.complete_kid_task(hits[0]['id'])
    import main as _m
    emoji = _m._TASK_EMOJI.get(hits[0].get('kind'), '📌')
    return {"status": "success",
            "message": f"Checked off {emoji} '{hits[0].get('title')}' — nice work! ✅"}


# --- Shopping list (meals & provisioning arc M1) ---------------------------
# Voice/text is the primary capture path and ~80% of the value: the person who
# notices is rarely the person who shops. Adds are DIRECT for everyone
# including kids — an item costs the family nothing, so approval would be
# friction with no gate (docs/meal_design.md principle 4).

def _resolve_shopping_list(list_name: str = "") -> tuple:
    """(list, error_message). Falls back to the default list, which is created
    on first use so a fresh install never fails a voice add."""
    from services import storage
    low = (list_name or '').strip().lower()
    if not low:
        return storage.ensure_default_shopping_list(), None
    lists = storage.get_shopping_lists()
    hits = [l for l in lists if low == (l.get('name') or '').lower()
            or low == (l.get('store') or '').lower()]
    if not hits:
        hits = [l for l in lists if low in (l.get('name') or '').lower()
                or low in (l.get('store') or '').lower()]
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, (f"I don't have a list called '{list_name}'. "
                      + ("Lists: " + ", ".join(l.get('name') or '?' for l in lists)
                         if lists else "There aren't any lists yet."))
    return None, "Which list? " + ", ".join(l.get('name') or '?' for l in hits)


def add_shopping_items(items: str, list_name: str = "",
                       acting_member: dict = None) -> Dict[str, Any]:
    """Add one or more things to a shopping list. Direct action, never a
    proposal — see module note."""
    import re
    from services import storage
    from models.schemas import ShoppingItem
    lst, err = _resolve_shopping_list(list_name)
    if err:
        return {"status": "error", "message": err}
    raw = [p.strip() for p in re.split(r',|\band\b|\n', items or '') if p.strip()]
    if not raw:
        return {"status": "error", "message": "What should I add to the list?"}
    added, already = [], []
    for name in raw:
        existing = storage.find_open_shopping_item(lst['id'], name)
        if existing:
            already.append(existing.get('name') or name)
            continue
        it = ShoppingItem(list_id=lst['id'], name=name, added_via='voice',
                          added_by=(acting_member or {}).get('id')).model_dump()
        storage.add_shopping_item(it)
        added.append(name)
    _bump_stream()
    parts = []
    if added:
        parts.append(f"Added to {lst.get('name')}: " + ", ".join(added) + ".")
    if already:
        parts.append(("Already on there: " if not added else "Already there: ")
                     + ", ".join(already) + ".")
    return {"status": "success", "message": " ".join(parts)}


def get_shopping_list_items(list_name: str = "",
                            acting_member: dict = None) -> Dict[str, Any]:
    """READ: what's still open on a shopping list."""
    from services import storage
    lst, err = _resolve_shopping_list(list_name)
    if err:
        return {"status": "error", "message": err}
    items = storage.get_shopping_items(lst['id'], include_checked=False)
    if not items:
        return {"status": "success",
                "message": f"{lst.get('name')} is empty — nothing needed."}
    lines = []
    for i in items:
        qty = f" ({i['qty']})" if i.get('qty') else ""
        lines.append(f"• {i.get('name')}{qty}")
    return {"status": "success",
            "message": f"{lst.get('name')} ({len(items)}):\n" + "\n".join(lines)}


def check_off_shopping_item(item_name: str, list_name: str = "",
                            acting_member: dict = None) -> Dict[str, Any]:
    """Check something off — the in-the-aisle path. Fuzzy match on open items."""
    from services import storage
    lst, err = _resolve_shopping_list(list_name)
    if err:
        return {"status": "error", "message": err}
    items = storage.get_shopping_items(lst['id'], include_checked=False)
    if not items:
        return {"status": "success", "message": f"{lst.get('name')} is already clear!"}
    low = (item_name or '').strip().lower()
    hits = [i for i in items if low == (i.get('name') or '').lower()] \
        or [i for i in items if low and low in (i.get('name') or '').lower()]
    if not hits:
        return {"status": "error",
                "message": f"I don't see '{item_name}' on {lst.get('name')}. Still open: "
                           + ", ".join(i.get('name') or '?' for i in items[:6])}
    if len(hits) > 1:
        return {"status": "error",
                "message": "Which one? " + ", ".join(i.get('name') or '?' for i in hits)}
    storage.check_shopping_item(hits[0]['id'], True, (acting_member or {}).get('id'))
    _bump_stream()
    left = len(items) - 1
    tail = " That's everything! 🎉" if left == 0 else f" {left} left."
    return {"status": "success",
            "message": f"Got {hits[0].get('name')}.{tail}"}


def remove_shopping_item_by_name(item_name: str, list_name: str = "",
                                 acting_member: dict = None) -> Dict[str, Any]:
    """Take something off the list entirely (changed our mind, not bought)."""
    from services import storage
    lst, err = _resolve_shopping_list(list_name)
    if err:
        return {"status": "error", "message": err}
    items = storage.get_shopping_items(lst['id'], include_checked=False)
    low = (item_name or '').strip().lower()
    hits = [i for i in items if low == (i.get('name') or '').lower()] \
        or [i for i in items if low and low in (i.get('name') or '').lower()]
    if not hits:
        return {"status": "error",
                "message": f"'{item_name}' isn't on {lst.get('name')}."}
    if len(hits) > 1:
        return {"status": "error",
                "message": "Which one? " + ", ".join(i.get('name') or '?' for i in hits)}
    storage.delete_shopping_item(hits[0]['id'])
    _bump_stream()
    return {"status": "success",
            "message": f"Took {hits[0].get('name')} off {lst.get('name')}."}


def get_eating_plan(target_date: str = "today", acting_member: dict = None) -> Dict[str, Any]:
    """READ: what tonight's eating actually looks like given the schedule —
    the cook window, who eats where and when, what has to be packed, and
    whether anyone has no gap at all (meals arc M2)."""
    import datetime as _dt
    from services import meals, storage
    day = _parse_fuzzy_date(target_date or 'today')
    plan = meals.eating_plan(day.isoformat(), 'dinner')
    when = "Tonight" if day == _dt.date.today() else day.strftime('%A')

    if not plan.get('people'):
        return {"status": "success", "message": "I don't have anyone to plan around yet."}
    if plan.get('nobody_can_eat'):
        return {"status": "success",
                "message": f"{when} nobody has a real gap to eat — everyone's booked "
                           "straight through dinner. Worth grabbing something on the way."}

    lines = meals.plan_summary_lines(plan)
    if not lines:
        window = plan.get('cook_window_mins') or 0
        return {"status": "success",
                "message": f"{when} is an easy one — everyone's home for dinner"
                           + (f" and there's about {window} min to cook." if window
                              else ".")}
    return {"status": "success", "message": f"{when}: " + " ".join(lines)}


def suggest_dinner(target_date: str = "today", acting_member: dict = None) -> Dict[str, Any]:
    """READ: which of the family's own meals actually fit today's schedule.
    A filter over the repertoire, not a planning exercise (meals arc M3)."""
    import datetime as _dt
    from services import meals
    day = _parse_fuzzy_date(target_date or 'today')
    plan = meals.eating_plan(day.isoformat(), 'dinner')
    when = "tonight" if day == _dt.date.today() else day.strftime('%A')

    if plan.get('nobody_can_eat'):
        return {"status": "success",
                "message": f"Nobody has a real gap to eat {when} — everyone's booked "
                           "through dinner. Worth grabbing something on the way."}
    res = meals.meals_that_fit(plan, limit=4)
    if res.get('empty'):
        return {"status": "success",
                "message": "There's nothing in the repertoire yet. Tell me a few "
                           "things you make on a weeknight and I'll add them."}
    fits = res.get('fits') or []
    if not fits:
        blocked = res.get('blocked') or []
        why = blocked[0].get('why') if blocked else "the window's too tight"
        return {"status": "success",
                "message": f"Nothing in the repertoire fits {when} — {why}. "
                           "Might be a night to pick something up."}

    window = plan.get('cook_window_mins') or 0
    head = f"About {window} min at home {when}" if window else f"Not much time {when}"
    if plan.get('packed_count'):
        head += f", and {plan['packed_count']} eating out of the house"
    lines = []
    for m in fits:
        hands = int(m.get('prep_ahead_mins') or 0) + int(m.get('finish_mins') or 0)
        bits = [f"{hands} min hands-on" if hands else "nothing to make"]
        if m.get('unattended_mins'):
            bits.append(f"{m['unattended_mins']} min in the oven")
        if m.get('needs_ahead') not in (None, '', 'none'):
            bits.append(f"needs a {m['needs_ahead'].replace('_', ' ')} head start")
        lines.append(f"• {m['name']} — {', '.join(bits)}")
    return {"status": "success", "message": f"{head}. These fit:\n" + "\n".join(lines)}


def add_meal_to_repertoire(name: str, acting_member: dict = None) -> Dict[str, Any]:
    """Add one of the family's meals from their OWN WORDS — a bare name
    ("tacos") or a whole plate written out ("chicken, rice, beans (black, red,
    or pinto), veggies, salad"). A short display name and the components are
    derived; everything is correctable later."""
    from services import storage, meals
    name = (name or '').strip()
    if not name:
        return {"status": "error", "message": "What's the meal called?"}
    existing = storage.find_meal_by_name(name)
    if existing:
        return {"status": "success",
                "message": f"{existing['name']} is already in the repertoire."}
    meal = meals.create_meal_from_dishes(name)
    from services import storage as _st
    plate = meals.compose_meal(meal)
    hands = int(plate.get('prep_ahead_mins') or 0) + int(plate.get('finish_mins') or 0)
    parts = [d.get('short_name') or d.get('name') for d in plate.get('dishes') or []]
    vague = [d for d in plate.get('dishes') or [] if d.get('needs_detail')]
    fresh = [i['name'] for i in meal.get('ingredients') or [] if i.get('kind') == 'fresh']
    if parts:
        bits = [f"about {hands} min hands-on"] if hands else []
        msg = f"Added {meal['name']} — " + ", ".join(parts) + "."
        if bits:
            msg += f" I've got it at {bits[0]}."
        if vague:
            q = vague[0].get('detail_question') or f"What kind of {vague[0].get('short_name')}?"
            msg += f" One thing: {q}"
        return {"status": "success", "message": msg}
    bits = []
    if hands:
        bits.append(f"about {hands} min hands-on")
    if fresh:
        bits.append("needs " + ", ".join(fresh[:4]))
    if not bits:
        # Enrichment was unavailable (no key / model down) — say so plainly
        # rather than implying we worked something out.
        return {"status": "success",
                "message": f"Added {meal['name']} to the repertoire."}
    return {"status": "success",
            "message": f"Added {meal['name']} — I've got it at "
                       + " and it ".join(bits) + ". Tell me if that's off."}


def add_meal_ingredients_to_list(meal_name: str, list_name: str = "",
                                 acting_member: dict = None) -> Dict[str, Any]:
    """Put a meal's fresh ingredients on the shopping list. Staples never go —
    the family already has those."""
    from services import storage, meals
    meal = storage.find_meal_by_name(meal_name)
    if not meal:
        return {"status": "error",
                "message": f"I don't have '{meal_name}' in the repertoire."}
    lst, err = _resolve_shopping_list(list_name)
    if err:
        return {"status": "error", "message": err}
    res = meals.ingredients_to_shopping(meal, lst['id'],
                                        added_by=(acting_member or {}).get('id'))
    _bump_stream()
    if res.get('reason'):
        return {"status": "success",
                "message": f"{meal['name']} is takeout — nothing to buy for it."}
    if not res['added']:
        return {"status": "success",
                "message": f"Everything {meal['name']} needs is either a staple "
                           "or already on the list."}
    return {"status": "success",
            "message": f"Added for {meal['name']}: " + ", ".join(res['added']) + "."}


def get_tonights_plate(target_date: str = "today", acting_member: dict = None) -> Dict[str, Any]:
    """READ: what's actually planned for dinner — the entree, the sides and
    any dessert, composed against today's schedule."""
    import datetime as _dt
    from services import meals
    day = _parse_fuzzy_date(target_date or 'today')
    plan = meals.eating_plan(day.isoformat(), 'dinner')
    plate = meals.get_or_compose_plate(day.isoformat(), plan)
    when = "Tonight" if day == _dt.date.today() else day.strftime('%A')
    if not plate['dishes']:
        return {"status": "success",
                "message": f"{when} there's nothing to build a plate from yet — "
                           "tell me a few things you cook and I'll add them."}
    totals = meals.plate_totals(plate['dishes'], day.isoformat())
    hands = int(totals.get('prep_ahead_mins') or 0) + int(totals.get('finish_mins') or 0)
    names = [d.get('short_name') or d['name'] for d in plate['dishes']]
    tail = f" About {hands} min hands-on" if hands else ""
    if totals.get('unattended_mins'):
        tail += f", {totals['unattended_mins']} in the oven"
    verb = "You've set" if plate['edited'] else "I'd suggest"
    return {"status": "success",
            "message": f"{when}: {verb} " + ", ".join(names) + f".{tail}."}


def schedule_shopping_trip(store: str = "", list_name: str = "",
                           weekly: bool = True,
                           acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "schedule a grocery run" / "we need a shopping trip" — creates the
    errand bound to a list, which the solver then places against the week."""
    from services import storage, shopping
    lst = None
    if list_name:
        lst = next((l for l in storage.get_shopping_lists()
                    if (l.get('name') or '').strip().lower() == list_name.strip().lower()),
                   None)
        if not lst:
            return {"status": "error", "message": f"I don't have a list called '{list_name}'."}
    lst = lst or storage.ensure_default_shopping_list()
    res = shopping.create_errand_for_list(lst['id'], location=(store or '').strip() or None,
                                          recurring=bool(weekly))
    return {"status": "error" if res['status'] == 'error' else "success",
            "message": res['message']}


def get_shopping_trip(list_name: str = "", acting_member: dict = None) -> Dict[str, Any]:
    """READ: "when are we going shopping" — the SCHEDULED trip if the solver has
    placed it, which beats any weekday rule."""
    from services import storage, shopping
    lst = None
    if list_name:
        lst = next((l for l in storage.get_shopping_lists()
                    if (l.get('name') or '').strip().lower() == list_name.strip().lower()),
                   None)
    lst = lst or storage.ensure_default_shopping_list()
    n = len(storage.get_shopping_items(lst['id'], include_checked=False))
    nxt = shopping.next_scheduled_shop(lst['id'])
    if not nxt:
        return {"status": "success",
                "message": f"There's no trip scheduled for {lst['name']} — "
                           f"{n} thing{'s' if n != 1 else ''} waiting on it. "
                           "Want me to add one?"}
    if not nxt.get('scheduled'):
        return {"status": "success",
                "message": f"{nxt['errand']['title']} is set up but hasn't been "
                           f"placed in the week yet. {n} thing"
                           f"{'s' if n != 1 else ''} on the list."}
    return {"status": "success",
            "message": f"{nxt['label']} at {nxt['time_label']} — "
                       f"{nxt['errand']['location']}, {n} thing"
                       f"{'s' if n != 1 else ''} on the list."}


def set_meal_rule(description: str, kind: str = "frequency_cap",
                  tags: str = "", dish_names: str = "", takeout: bool = False,
                  max_servings: int = 1, window_days: int = 7,
                  dwell_days: int = 3, except_dishes: str = "",
                  acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: how this household EATS. "we only eat meat about once a week",
    "takeout now and then", "we cook one kind of beans at a time and eat it a
    few days before making the next"."""
    from services import storage, meals
    tag_list = [t.strip().lower()
                for t in str(tags or '').replace(' and ', ',').split(',')
                if t.strip()]
    ids, missing = [], []
    for nm in [n.strip() for n in str(dish_names or '').replace(' and ', ',').split(',')
               if n.strip()]:
        d = storage.find_dish_by_name(nm)
        (ids.append(d['id']) if d else missing.append(nm))
    # "the beans, but not baked beans" — a tag is nearly always almost right.
    excl = []
    for nm in [n.strip() for n in str(except_dishes or '').replace(' and ', ',').split(',')
               if n.strip()]:
        d = storage.find_dish_by_name(nm)
        (excl.append(d['id']) if d else missing.append(nm))
    res = meals.add_meal_rule(description, kind, tags=tag_list, dish_ids=ids,
                              exclude_dish_ids=excl,
                              sources=['ordered'] if takeout else [],
                              max_servings=max_servings, window_days=window_days,
                              dwell_days=dwell_days)
    said = meals.describe_meal_rule(res['rule'])
    if not res['match_count']:
        return {"status": "success",
                "message": f"Noted ({said}) - but it does not match any dish I "
                           "know yet, so it will not do anything. Tell me which "
                           "dishes it covers and I will attach it."}
    tail = f" (I do not have {', '.join(missing)} yet.)" if missing else ""
    return {"status": "success",
            "message": f"Got it - {said}. That covers "
                       f"{', '.join(res['matches'][:6])}"
                       f"{'...' if res['match_count'] > 6 else ''}.{tail}"}


def get_meal_rules(acting_member: dict = None) -> Dict[str, Any]:
    """READ: what rules do you have for our meals."""
    from services import storage, meals
    rules = storage.get_meal_rules()
    if not rules:
        return {"status": "success",
                "message": "No meal rules set - I am just rotating what you cook."}
    return {"status": "success",
            "message": "Your meal rules: "
                       + "; ".join(meals.describe_meal_rule(r) for r in rules) + "."}


def plan_specific_dinner(target_date: str, dish_names: str = "", note: str = "",
                         acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "steak on Monday, it's Mom's birthday", "Grandma is bringing
    dinner Tuesday". Sets a night and LOCKS it so the composer never touches
    it. Dishes are optional — a locked night with no dishes is exactly how
    "someone else is feeding us" is said."""
    import datetime as _dt
    from services import storage, meals
    day = _parse_fuzzy_date(target_date or 'today')
    wanted = [n.strip() for n in str(dish_names or '').replace(' and ', ',').split(',')
              if n.strip()]
    found, missing = [], []
    for nm in wanted:
        d = storage.find_dish_by_name(nm)
        (found.append(d) if d else missing.append(nm))
    if wanted and not found:
        return {"status": "error",
                "message": f"I don't have {', '.join(missing)} in what you cook. "
                           "Add it and I'll set it for that night."}
    res = meals.set_plate_lock(day.isoformat(), True, (note or '').strip() or None,
                               [d['id'] for d in found] if found else
                               ([] if wanted else None))
    when = "tonight" if day == _dt.date.today() else day.strftime('%A')
    names = ', '.join(d.get('short_name') or d['name'] for d in res['dishes'])
    head = (f"{when.capitalize()} is set: {names}" if names
            else f"{when.capitalize()} is spoken for")
    tail = f" — {res['note']}" if res.get('note') else ""
    miss = f" (I don't have {', '.join(missing)} yet.)" if missing else ""
    return {"status": "success",
            "message": f"{head}{tail}. I won't change it.{miss}"}


def unlock_dinner(target_date: str, acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "never mind about Monday" — hands the night back to the composer."""
    import datetime as _dt
    from services import meals
    day = _parse_fuzzy_date(target_date or 'today')
    meals.reset_plate(day.isoformat(), force=True)
    when = "tonight" if day == _dt.date.today() else day.strftime('%A')
    return {"status": "success",
            "message": f"{when.capitalize()} is back to being proposed."}


def pair_dishes(dish_name: str, partner_names: str, exclusive: bool = False,
                acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "brisket always comes with beans and fries", "the rice only ever
    goes with the curry". Directed — the partners stay free to appear on their
    own unless `exclusive` says otherwise."""
    from services import storage, meals
    dish = storage.find_dish_by_name(dish_name)
    if not dish:
        return {"status": "error",
                "message": f"I don't have a dish called '{dish_name}'."}
    wanted = [p.strip() for p in str(partner_names or '').replace(' and ', ',').split(',')
              if p.strip()]
    found, missing = [], []
    for nm in wanted:
        p = storage.find_dish_by_name(nm)
        (found.append(p) if p else missing.append(nm))
    if not found:
        return {"status": "error",
                "message": f"I couldn't find {', '.join(missing) or 'those dishes'} "
                           "in what you cook. Add them first and I'll pair them up."}
    nm = dish.get('short_name') or dish['name']
    if exclusive:
        # "X only ever goes with Y" is a statement about X, recorded on X.
        meals.set_pairing(dish['id'], [p['id'] for p in found], 'only_with')
        names = ', '.join(p.get('short_name') or p['name'] for p in found)
        return {"status": "success",
                "message": f"Got it — {nm} only comes up with {names}."}
    meals.set_pairing(dish['id'], [p['id'] for p in found], 'always_with')
    names = ', '.join(p.get('short_name') or p['name'] for p in found)
    tail = (f" (I don't have {', '.join(missing)} yet.)" if missing else "")
    return {"status": "success",
            "message": f"Got it — {nm} always comes with {names}.{tail}"}


def _find_occasion(name: str) -> Optional[dict]:
    from services import storage
    low = (name or '').strip().lower()
    rows = storage.get_occasions(include_done=True)
    if not low:
        return rows[0] if rows else None
    for o in rows:
        if (o.get('title') or '').strip().lower() == low:
            return o
    for o in rows:
        if low in (o.get('title') or '').strip().lower() or low == (o.get('kind') or ''):
            return o
    return None


def add_occasion(title: str, anchor_date: str, kind: str = "gathering",
                 window_start: str = "", window_end: str = "",
                 dish_tags: str = "", acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "Thanksgiving is on the 26th and my parents are here from the
    25th to the 29th", "Ellie's birthday party is on the 14th"."""
    from services import occasions as _occ
    if not (title or '').strip():
        return {"status": "error", "message": "What should I call it?"}
    day = _parse_fuzzy_date(anchor_date or 'today')
    tags = [t.strip().lower() for t in str(dish_tags or '').replace(' and ', ',').split(',')
            if t.strip()]
    o = _occ.create(title, day.isoformat(), kind,
                    (window_start or '').strip() or None,
                    (window_end or '').strip() or None, tags)
    lo, hi = _occ.window(o)
    span = "" if lo == hi else f", running {lo.strftime('%a %-d')} to {hi.strftime('%a %-d')}" \
        if hasattr(lo, 'strftime') else ""
    prior = " I've linked it to last year's, so I can tell you what's missing." \
        if o.get('prior_occasion_id') else ""
    return {"status": "success",
            "message": f"Got it — {o['title']} on {day.strftime('%A %d %B')}{span}.{prior}"}


def get_occasion(occasion_name: str = "", acting_member: dict = None) -> Dict[str, Any]:
    """READ: "what's the state of Thanksgiving?", "who's coming to the party?"."""
    from services import occasions as _occ
    o = _find_occasion(occasion_name)
    if not o:
        return {"status": "success",
                "message": "I don't have any occasions on the books yet."}
    c = _occ.contents(o['id'])
    away = c.get('days_away')
    bits = [f"{o['title']} — {o['anchor_date']}"
            + (f", {away} days away" if isinstance(away, int) and away >= 0 else "")
            + f". {c['headcount']} people eating."]
    if c['guests']:
        bits.append("Coming: " + ', '.join(
            g['name'] + (f" ×{g['headcount']}" if g['headcount'] > 1 else '')
            for g in c['guests']) + ".")
    if c['lists']:
        bits.append("Lists: " + ', '.join(l['name'] for l in c['lists']) + ".")
    if c['loose_items']:
        bits.append(f"{len(c['loose_items'])} things for it on the regular shopping list.")
    if c['errands']:
        left = [e for e in c['errands'] if not e.get('is_completed')]
        bits.append(f"{len(left)} of {len(c['errands'])} errands still to do.")
    if not (c['guests'] or c['lists'] or c['errands'] or c['loose_items']):
        bits.append("Nothing attached to it yet.")
    return {"status": "success", "message": ' '.join(bits)}


def get_occasion_insights(occasion_name: str = "", acting_member: dict = None) -> Dict[str, Any]:
    """READ: "how's Thanksgiving looking?", "is anything going to go wrong with
    the party?", "who's doing all the work for this?"

    The part a checklist cannot do. Uses what only this app knows — who is
    driving, where the schedule has slack, how this family cooks — and says it
    plainly. Names an imbalance, never scores it.
    """
    from services import occasions as _occ
    o = _find_occasion(occasion_name)
    if not o:
        return {"status": "success",
                "message": "I don't have any occasions on the books yet."}
    rows = _occ.insights(o['id']).get('insights') or []
    if not rows:
        return {"status": "success",
                "message": f"{o['title']} looks straightforward from here — "
                           "nothing clashing and nothing waiting on a decision."}
    return {"status": "success",
            "message": f"{o['title']}: " + " ".join(r['text'] for r in rows[:5])}


def get_occasion_gaps(occasion_name: str = "", acting_member: dict = None) -> Dict[str, Any]:
    """READ: "what still needs doing for Thanksgiving?", "am I forgetting
    anything for the party?"

    A DIFF, not an inventory. Listing what exists cannot answer "have I
    forgotten anything" — the gap is invisible by construction — so this
    compares against the usual shape of this kind of occasion and against last
    year's. Ordered by slack, and it never quotes a percentage: six of
    fourteen presents unbought is fine in October and an emergency on the 23rd.
    """
    from services import occasions as _occ
    o = _find_occasion(occasion_name)
    if not o:
        return {"status": "success",
                "message": "I don't have any occasions on the books yet."}
    rep = _occ.gap_report(o['id'])
    gaps, qs = rep.get('gaps') or [], rep.get('questions') or []
    away = rep.get('days_away')
    head = f"{o['title']}" + (f", {away} days away" if isinstance(away, int) and away >= 0
                              else "") + "."
    if not gaps:
        tail = (" Nothing outstanding against the usual list"
                + (" or last year's." if rep.get('has_prior')
                   else " — there's no previous one to compare with yet."))
        if qs:
            tail += f" I still don't know: {qs[0]['ask']}"
        return {"status": "success", "message": head + tail}
    lines = []
    for g in gaps[:6]:
        when = ("overdue" if g['slack_days'] < 0
                else "today" if g['slack_days'] == 0
                else f"{g['slack_days']} days")
        note = f" ({g['note']})" if g.get('note') else ""
        lines.append(f"{g['label']} — {when}{note}")
    msg = head + " Still to sort: " + "; ".join(lines) + "."
    if qs:
        msg += f" And I still don't know: {qs[0]['ask']}"
    return {"status": "success", "message": msg}


def set_occasion_attendance(occasion_name: str, who: str, coming: bool = True,
                            acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "Grandad isn't coming to Thanksgiving this year", "Sarah's away
    for the party", "actually Marta is joining us for Christmas".

    Household members only — anybody outside the family is `add_occasion_guests`.
    Answers with the new headcount, because that is the number that changes
    every plate in the window.
    """
    from services import storage, occasions as _occ
    o = _find_occasion(occasion_name)
    if not o:
        return {"status": "error",
                "message": f"I don't have an occasion called '{occasion_name}'."}
    low = (who or '').strip().lower()
    member = next((m for m in storage.get_all_members()
                   if (m.get('name') or '').strip().lower() == low), None)
    if not member:
        member = next((m for m in storage.get_all_members()
                       if low and low in (m.get('name') or '').strip().lower()), None)
    if not member:
        return {"status": "error",
                "message": f"'{who}' isn't in the family — if they're a guest, "
                           "tell me who's coming instead and I'll add them."}
    _occ.set_attendance(o['id'], member['id'], coming)
    n = _occ.headcount(o['id'])
    verb = "is coming to" if coming else "is not coming to"
    return {"status": "success",
            "message": f"Noted — {member['name']} {verb} {o['title']}. "
                       f"That's {n} eating now."}


def add_occasion_guests(occasion_name: str, who: str, headcount: int = 1,
                        cannot_eat: str = "", acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "the Wilsons are coming, there are four of them", "Grandma's
    coming and she can't have shellfish".

    A guest's allergy binds exactly like a family member's — the meal planner
    stops proposing it — which is the whole reason the guest list exists at
    all, given this app deliberately does not send invitations.
    """
    from services import occasions as _occ
    o = _find_occasion(occasion_name)
    if not o:
        return {"status": "error",
                "message": f"I don't have an occasion called '{occasion_name}'."}
    avoid = [t.strip().lower() for t in str(cannot_eat or '').replace(' and ', ',').split(',')
             if t.strip()]
    g = _occ.add_guest(o['id'], who, headcount, dietary_avoid=avoid)
    n = _occ.headcount(o['id'])
    tail = (f" I'll keep {', '.join(avoid)} off the plan." if avoid else "")
    return {"status": "success",
            "message": f"Added {g['name']}"
                       + (f" (×{g['headcount']})" if g['headcount'] > 1 else "")
                       + f" to {o['title']} — that's {n} eating now.{tail}"}


def source_for_occasion(occasion_name: str, needed: str,
                        acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "I need party favours for a shark party", "we need decorations
    and paper plates for sixteen"."""
    from services import occasions as _occ
    o = _find_occasion(occasion_name)
    if not o:
        return {"status": "error",
                "message": f"I don't have an occasion called '{occasion_name}'."}
    res = _occ.generate_list(o['id'], needed,
                             added_by=(acting_member or {}).get('id'))
    if res.get('error'):
        return {"status": "error", "message": f"Couldn't work that out — {res['error']}."}
    names = ', '.join(i['name'] for i in res['items'][:6])
    more = f" and {len(res['items']) - 6} more" if len(res['items']) > 6 else ""
    return {"status": "success",
            "message": f"Built a list of {len(res['items'])} for {o['title']} "
                       f"({res['headcount']} people): {names}{more}. It's on the "
                       "Shopping page — check it over and it'll go to a cart."}


def get_run_sheet(target_date: str = "today", serve_at: str = "",
                  acting_member: dict = None) -> Dict[str, Any]:
    """READ: "when do I need to start cooking on Thursday?", "what time does
    the turkey go in?"

    Pull, never push. This is the taskmaster line the meals arc drew: a run
    sheet is something somebody asks for, and the moment it starts arriving on
    its own it is a stream of orders.
    """
    from services import meals
    day = _parse_fuzzy_date(target_date or 'today')
    sheet = meals.plate_run_sheet(day.isoformat(), (serve_at or '').strip() or None)
    if not sheet.get('steps'):
        return {"status": "success",
                "message": "There's nothing to cook on that night yet — pick "
                           "some dishes and I'll work out the timings."}
    head = (f"Start at {sheet['start_at']} to eat at {sheet['serve_at']}"
            + (f", {sheet['cooks']} of you cooking" if (sheet.get('cooks') or 1) > 1 else "")
            + ".")
    lines = [f"{s['at']} — {s['text']}" for s in sheet['steps']]
    return {"status": "success", "message": head + "\n" + "\n".join(lines),
            "start_at": sheet['start_at'], "serve_at": sheet['serve_at']}


def set_hosting(target_date: str, serving_for: int = 0, cooks: int = 0,
                acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "we're having twelve people on Saturday", "four of us are cooking
    Thursday", "it's just us again on the 20th".

    Answers with the consequence rather than a confirmation. "Saved" is not
    what anybody wants from this — how long the evening now takes, and whether
    the oven can actually do it, is the reason they said it out loud.
    """
    import datetime as _dt
    from services import meals
    day = _parse_fuzzy_date(target_date or 'today')
    res = meals.set_plate_hosting(day.isoformat(), serving_for, cooks)
    n, hands = res.get('serving_for'), int(res.get('hands_on_mins') or 0)
    when = "tonight" if day == _dt.date.today() else day.strftime('%A')
    if not n:
        return {"status": "success",
                "message": f"Back to an ordinary night on {when}."}
    who = f"{res['cooks']} of you cooking" if (res.get('cooks') or 1) > 1 else "just you cooking"
    bits = [f"{when}: cooking for {n}, {who}."]
    if hands:
        hrs = round(hands / 60.0, 1)
        bits.append(f"That's about {hands} min hands-on"
                    + (f" ({hrs}h)" if hands >= 90 else "") + ".")
    clashes = res.get('oven_conflicts') or []
    if clashes:
        temps = ', '.join(f"{c['temp_f']}°" for c in clashes)
        bits.append(f"Heads up — you've got one oven and {len(clashes)} "
                    f"temperatures on that plate ({temps}), so they have to "
                    "take turns.")
    return {"status": "success", "message": ' '.join(bits)}


def set_dish_scope(dish_name: str, occasion_only: bool = True,
                   acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "turkey is only for holidays", "we eat deviled eggs at parties,
    not on a Tuesday" — and the reverse, "the ham is fine any time".

    Says PROPOSAL, not availability, in the reply on purpose: the family must
    not come away thinking the dish is gone. It still shows in every picker,
    and leftovers of it still land on ordinary plates.
    """
    from services import storage
    dish = storage.find_dish_by_name(dish_name)
    if not dish:
        return {"status": "error",
                "message": f"I don't have a dish called '{dish_name}'."}
    scope = 'occasion' if occasion_only else 'everyday'
    storage.update_dish(dish['id'], {'scope': scope})
    nm = dish.get('short_name') or dish['name']
    if occasion_only:
        return {"status": "success",
                "message": f"Got it — {nm} is holiday and party food now. I "
                           "won't suggest it on an ordinary night, but it's "
                           "still there to pick, and leftovers of it still count."}
    return {"status": "success",
            "message": f"Got it — {nm} is back in the everyday rotation."}


def set_dish_categories(dish_name: str, categories: str = "",
                        whole_meal: bool = None, serves: int = None,
                        whole_units: bool = None,
                        acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "black beans are a protein, not just a starch", "spaghetti and
    meat sauce is a whole meal", "the chili serves eight".

    The correction path for what a dish IS. Categories are the FAMILY'S own,
    so an unknown one is reported rather than invented — the agent must not
    quietly create vocabulary nobody chose.
    """
    from services import storage, meals as _meals
    dish = storage.find_dish_by_name(dish_name)
    if not dish:
        return {"status": "error",
                "message": f"I don't have a dish called '{dish_name}'."}
    nm = dish.get('short_name') or dish['name']
    patch, said = {}, []
    wanted = [c.strip() for c in (categories or '').split(',') if c.strip()]
    if wanted:
        ids = _meals.resolve_category_names(wanted)
        if not ids:
            known = ', '.join(c['name'] for c in storage.get_dish_categories())
            return {"status": "error",
                    "message": f"I don't have a category called "
                               f"'{wanted[0]}'. You have: {known or 'none yet'}."}
        patch['category_ids'] = ids
        names = [c['name'] for c in storage.get_dish_categories() if c['id'] in ids]
        said.append("counts as " + " or ".join(names))
    if whole_meal is not None:
        patch['type'] = 'meal' if whole_meal else 'dish'
        said.append("a whole dinner on its own" if whole_meal
                    else "one part of a plate")
    if serves is not None:
        try:
            patch['serves'] = max(1, min(50, int(serves)))
            said.append(f"serves {patch['serves']}")
        except (TypeError, ValueError):
            pass
    if whole_units is not None:
        patch['whole_units'] = bool(whole_units)
        said.append("made by the tray" if whole_units
                    else "something you can make more or less of")
    if not patch:
        return {"status": "error",
                "message": "Tell me what to change — the categories, whether "
                           "it's a whole meal, how many it serves, or whether "
                           "it's made in whole trays."}
    storage.update_dish(dish['id'], patch)
    return {"status": "success",
            "message": f"Got it — {nm} " + ", ".join(said) + "."}


def unpair_dishes(dish_name: str, partner_name: str = "",
                  acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "brisket doesn't always come with fries anymore"."""
    from services import storage, meals
    dish = storage.find_dish_by_name(dish_name)
    if not dish:
        return {"status": "error", "message": f"I don't have a dish called '{dish_name}'."}
    pid = None
    if (partner_name or '').strip():
        p = storage.find_dish_by_name(partner_name)
        pid = p['id'] if p else None
    total = 0
    for mode in ('always_with', 'only_with'):
        total += meals.clear_pairing(dish['id'], pid, mode).get('removed', 0)
    nm = dish.get('short_name') or dish['name']
    if not total:
        return {"status": "success", "message": f"{nm} wasn't paired with that anyway."}
    return {"status": "success", "message": f"Done — {nm} isn't tied to that now."}


def set_dish_prep(dish_name: str, action: str, when: str = "hours_before",
                  hours: float = 1.0, acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "we soak the rice the night before", "the chicken marinates an
    hour first". Attaches prep that happens OUTSIDE the cook window to a dish,
    with the reminder that goes with it."""
    from services import storage, meals
    dish = storage.find_dish_by_name(dish_name)
    if not dish:
        return {"status": "error",
                "message": f"I don't have a dish called '{dish_name}'. Want me to add it?"}
    res = meals.add_prep_step(dish['id'], action, when, hours)
    if res.get('status') != 'success':
        return {"status": "error", "message": res.get('message') or "That didn't work."}
    from models.schemas import PrepStep
    label = PrepStep(**{k: v for k, v in res['step'].items()
                        if k in ('action', 'when', 'hours', 'note', 'id')}).label()
    nm = dish.get('short_name') or dish['name']
    return {"status": "success",
            "message": f"Got it — {nm}: {label}. I'll remind you."}


def clear_dish_prep(dish_name: str, action: str = "",
                    acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "we don't soak the rice anymore"."""
    from services import storage, meals
    dish = storage.find_dish_by_name(dish_name)
    if not dish:
        return {"status": "error", "message": f"I don't have a dish called '{dish_name}'."}
    res = meals.remove_prep_step(dish['id'], (action or '').strip() or None)
    nm = dish.get('short_name') or dish['name']
    if not res.get('removed'):
        return {"status": "success", "message": f"{nm} didn't have that set anyway."}
    return {"status": "success", "message": f"Done — no more {action or 'prep'} for {nm}."}


def get_prep_ahead(acting_member: dict = None) -> Dict[str, Any]:
    """READ: "is there anything I need to do tonight for tomorrow?" — the
    soaking-and-marinating question the plate could never answer."""
    import datetime as _dt
    from services import meals, storage
    now = _dt.datetime.now()
    settings = storage.get_settings() or {}
    lines = []
    for i in range(2):
        date_str = (now.date() + _dt.timedelta(days=i)).isoformat()
        plan = meals.eating_plan(date_str, 'dinner', settings=settings)
        plate = meals.get_or_compose_plate(date_str, plan, settings)
        for dish in plate['dishes']:
            for step in meals.dish_prep_steps(dish):
                due = meals.prep_step_due_at(step, date_str, settings, plan)
                if due < now - _dt.timedelta(hours=6) or due > now + _dt.timedelta(hours=30):
                    continue
                nm = dish.get('short_name') or dish['name']
                when_txt = ("now" if due <= now else due.strftime('%I:%M %p').lstrip('0'))
                for_txt = "tonight" if i == 0 else "tomorrow"
                lines.append(f"{step['action']} the {nm} for {for_txt} ({when_txt})")
    if not lines:
        return {"status": "success",
                "message": "Nothing needs doing ahead for the next couple of days."}
    return {"status": "success", "message": "Ahead of time: " + "; ".join(lines) + "."}


def get_week_dinners(acting_member: dict = None) -> Dict[str, Any]:
    """READ: the dinners planned for the span the next grocery run covers —
    the answer to "what are we eating this week" and "what do I need to buy
    for"."""
    from services import meals
    win = meals.plan_window()
    week = meals.compose_week(win['start'], win['days'])
    if not any(d['dishes'] for d in week):
        return {"status": "success",
                "message": "There's nothing to build a week from yet — tell me a "
                           "few things you cook and I'll plan it out."}
    shop = datetime.date.fromisoformat(win['grocery_date']).strftime('%A')
    head = (f"Shopping {shop}. The {len(week)} nights it covers:"
            if win['mode'] == 'planning'
            else f"{len(week)} nights left before {shop}'s shop:")
    lines = [f"{d['weekday']}: " + (", ".join(x.get('short_name') or x['name']
                                              for x in d['dishes']) or "nothing yet")
             + (" (pinned)" if d['pinned'] else "")
             for d in week]
    return {"status": "success", "message": head + " " + "; ".join(lines) + "."}


def approve_week_dinners(acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: "that looks good" / "plan the week" — pins every night in the
    window and puts the whole span's fresh ingredients on the shopping list."""
    from services import meals
    win = meals.plan_window()
    res = meals.approve_week(win['start'], win['days'],
                             added_by=(acting_member or {}).get('id'))
    if not res['day_count']:
        return {"status": "success", "message": "There's nothing planned to approve yet."}
    n = len(res['added'])
    if not n:
        return {"status": "success",
                "message": f"{res['day_count']} nights are set — everything they "
                           "need was already on the list."}
    return {"status": "success",
            "message": f"{res['day_count']} nights are set. Added {n} item"
                       f"{'s' if n != 1 else ''}: " + ", ".join(res['added'][:8])
                       + ("…" if n > 8 else "") + "."}


def change_tonights_plate(dish_name: str, action: str = "add",
                          target_date: str = "today",
                          acting_member: dict = None) -> Dict[str, Any]:
    """Add or drop a dish for one evening ("we've got corn too", "no salad
    tonight"). Adjusts THIS evening only — the repertoire is untouched."""
    import datetime as _dt
    from services import storage, meals
    day = _parse_fuzzy_date(target_date or 'today')
    dish = storage.find_dish_by_name(dish_name)
    if not dish:
        return {"status": "error",
                "message": f"I don't have a dish called '{dish_name}'. Want me to add it?"}
    when = "tonight" if day == _dt.date.today() else day.strftime('%A')
    if str(action or 'add').lower().startswith('rem') or str(action).lower() in ('drop', 'no'):
        res = meals.remove_from_plate(day.isoformat(), dish['id'])
        if res.get('unchanged'):
            return {"status": "success",
                    "message": f"{dish['name']} wasn't on {when}'s plate anyway."}
        left = [d.get('short_name') or d['name'] for d in res['dishes']]
        return {"status": "success",
                "message": f"Dropped {dish.get('short_name') or dish['name']}. "
                           f"{when.capitalize()}: " + ", ".join(left) + "."}
    res = meals.add_to_plate(day.isoformat(), dish['id'])
    if res.get('error'):
        return {"status": "error", "message": "I couldn't add that."}
    names = [d.get('short_name') or d['name'] for d in res['dishes']]
    return {"status": "success",
            "message": f"Added {dish.get('short_name') or dish['name']}. "
                       f"{when.capitalize()}: " + ", ".join(names) + "."}


def add_dishes(description: str, acting_member: dict = None) -> Dict[str, Any]:
    """Add things the family cooks to the repertoire, from their own words.
    Every alternative becomes its own dish."""
    from services import meals
    if not (description or '').strip():
        return {"status": "error", "message": "What do you make?"}
    res = meals.add_dishes_from_text(description)
    if res.get('error'):
        return {"status": "error", "message": "I couldn't work that out."}
    added = [d.get('short_name') or d['name'] for d in res['added']]
    if not added:
        return {"status": "success", "message": "I already had all of those."}
    return {"status": "success",
            "message": "Added " + ", ".join(added) + " to what you cook."}


def refine_meal_dish(dish_name: str, detail: str, acting_member: dict = None) -> Dict[str, Any]:
    """Answer a "which potatoes, and how?" question so the times and the
    shopping line get accurate."""
    from services import storage, meals
    dish = storage.find_dish_by_name(dish_name)
    if not dish:
        return {"status": "error", "message": f"I don't have a dish called '{dish_name}'."}
    updated = meals.refine_dish(dish['id'], detail)
    hands = int(updated.get('prep_ahead_mins') or 0) + int(updated.get('finish_mins') or 0)
    tail = f" — about {hands} min hands-on" if hands else ""
    return {"status": "success",
            "message": f"Got it: {updated['name']}{tail}."}


def mark_leftovers(what: str = "", target_date: str = "today", parts: str = "",
                   acting_member: dict = None) -> Dict[str, Any]:
    """'We're having leftovers tonight' / 'the rice is already made'. Stops the
    app holding cook time for food that already exists."""
    from models.schemas import Leftover
    from services import storage
    day = _parse_fuzzy_date(target_date or 'today')
    storage.prune_leftovers(day.isoformat())

    part_list = [p.strip() for p in (parts or '').replace(' and ', ',').split(',')
                 if p.strip()]
    meal = storage.find_meal_by_name(what) if what else None
    # Resolve named parts to real DISHES where we can: a dish carries its own
    # times, so "the rice is made" subtracts the rice's actual minutes rather
    # than a proportional guess.
    dish_ids = []
    for p in part_list:
        d = storage.find_dish_by_name(p)
        if d:
            dish_ids.append(d['id'])
    rec = Leftover(date=day.isoformat(),
                   meal_id=meal['id'] if meal else None,
                   label=(meal['name'] if meal else (what or '').strip() or None),
                   parts=part_list, dish_ids=dish_ids).model_dump()
    storage.add_leftover(rec)

    when = "tonight" if day == __import__('datetime').date.today() else day.strftime('%A')
    if part_list:
        return {"status": "success",
                "message": f"Noted — {', '.join(part_list)} already made for {when}. "
                           "I won't hold time for that."}
    label = rec['label'] or 'leftovers'
    return {"status": "success",
            "message": f"Noted — {label} {when}. Nothing to cook."}


def clear_leftovers(target_date: str = "today", what: str = "",
                    acting_member: dict = None) -> Dict[str, Any]:
    """Undo — plans change. Name a dish to un-mark just that one, or leave it
    off to clear the whole day."""
    from services import storage, meals
    day = _parse_fuzzy_date(target_date or 'today')
    if (what or '').strip():
        dish = storage.find_dish_by_name(what)
        if dish and meals.unmark_leftover_dish(day.isoformat(), dish['id']):
            return {"status": "success",
                    "message": f"OK — {dish.get('short_name') or dish['name']} "
                               "still needs making, then."}
        if dish:
            return {"status": "success",
                    "message": f"{dish.get('short_name') or dish['name']} "
                               "wasn't marked as already made."}
        return {"status": "error", "message": f"I don't have a dish called '{what}'."}
    n = storage.clear_leftovers(day.isoformat())
    if not n:
        return {"status": "success", "message": "There were no leftovers marked."}
    return {"status": "success", "message": "Cleared — back to cooking, then."}


def mark_meal_served(meal_name: str, acting_member: dict = None) -> Dict[str, Any]:
    """'We had tacos' — keeps rotation honest without anyone maintaining it."""
    from services import storage
    meal = storage.find_meal_by_name(meal_name)
    if not meal:
        from services import meals as _meals
        meal = _meals.create_meal(meal_name)
        storage.mark_meal_served(meal['id'])
        return {"status": "success",
                "message": f"Noted — and I've added {meal['name']} to the "
                           "repertoire while I'm at it."}
    storage.mark_meal_served(meal['id'])
    return {"status": "success", "message": f"Noted — {meal['name']} tonight. 👍"}


def _bump_stream():
    """Nudge the SSE clock so an open list view on someone else's phone
    updates without a refresh."""
    try:
        import time as _time
        import main as _m
        _m.LAST_UPDATE_TIME = _time.time()
    except Exception:
        pass


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
            "description": "Posts the 📊 'Family Week in Review' WEEKLY stats digest (driving per driver, kid activities, chores, rewards, routine streaks) into the family chat RIGHT NOW ('send the weekly digest', 'post the week in review again'). It also goes out automatically on its weekly schedule — this is the on-demand resend. NOT for a single day's schedule: 'today's digest' / 'tomorrow digest' / 'what does tomorrow look like' is get_drive_digest, which never posts anything.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "get_drive_digest",
            "description": "Shows the drive digest for a day as a read-only answer — drives per driver sorted by time with prep-kit items, plus the weather line ('show me today's digest', 'show me the tomorrow digest', 'what does Friday look like', 'what are Dad's drives tomorrow'). Posts nothing anywhere. target_date comes from the user's words: 'today' (the default), 'tomorrow', a weekday, or YYYY-MM-DD. Pass member_name for one person's drives; omit it for every driver.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD."},
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
            "name": "get_kid_tasks",
            "description": "Reads a child's school/deadline list — homework, tests, projects, things to bring ('what's due?', 'what's on Ben's list?', 'do I have homework?'). Read-only; children see their own list, parents can name any child or omit member_name for all kids.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string", "description": "Which child's list; omit for the speaker's own (children) or all kids (parents)."}
                },
                "required": []
            }
        },
        {
            "name": "add_kid_task",
            "description": "Adds a task to a child's school/deadline list ('I have a math worksheet due Friday', 'add a spelling test Thursday for Ben', 'remind me to bring my library book Tuesday'). A DIRECT action — a kid managing their own list needs no approval. NOT for calendar events or rides (use propose_family_action for those).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "What's due, e.g. 'Math worksheet'."},
                    "due_date": {"type": "string", "description": "When it's due: 'tomorrow', a weekday name, or YYYY-MM-DD."},
                    "member_name": {"type": "string", "description": "Which child (parents only; children always get their own list)."},
                    "kind": {"type": "string", "enum": ["homework", "test", "project", "bring", "other"], "description": "Task type — drives the emoji."}
                },
                "required": ["title", "due_date"]
            }
        },
        {
            "name": "complete_kid_task",
            "description": "Checks a task off a child's school list ('I finished my math worksheet', 'mark Ben's project done'). Fuzzy title match on open tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_title": {"type": "string", "description": "The task to check off."},
                    "member_name": {"type": "string", "description": "Which child (parents only)."}
                },
                "required": ["task_title"]
            }
        },
        {
            "name": "add_shopping_items",
            "description": "Adds one or more things to a shopping list ('we're out of milk', 'add eggs and butter to the list', 'put paper towels on the Costco list'). A DIRECT action for ANYONE including children — a list item costs nothing, so it never needs approval. NOT for errands or calendar events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {"type": "string", "description": "What to add. Multiple things may be comma- or 'and'-separated; they are split into separate items."},
                    "list_name": {"type": "string", "description": "Which list or store (e.g. 'Costco'). Omit for the family's default list."}
                },
                "required": ["items"]
            }
        },
        {
            "name": "get_shopping_list_items",
            "description": "Reads what is still needed on a shopping list ('what's on the grocery list?', 'what do we need at Costco?').",
            "parameters": {
                "type": "object",
                "properties": {
                    "list_name": {"type": "string", "description": "Which list or store. Omit for the default list."}
                },
                "required": []
            }
        },
        {
            "name": "check_off_shopping_item",
            "description": "Checks something off the shopping list because it is now in the cart ('got the milk', 'check off eggs'). Use this while shopping. Fuzzy match on open items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "The item that was picked up."},
                    "list_name": {"type": "string", "description": "Which list or store. Omit for the default list."}
                },
                "required": ["item_name"]
            }
        },
        {
            "name": "get_eating_plan",
            "description": "Answers 'what's the plan for dinner?', 'do we have time to cook tonight?', 'who's eating when?' by reading the SCHEDULE — how long there is at home to cook, whether the family eats in shifts, who eats in the car and by when their food has to be ready, and whether anyone has no gap to eat at all. Use this for any question about fitting a meal into the day. It does NOT know what food is in the house.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD."}
                },
                "required": []
            }
        },
        {
            "name": "suggest_dinner",
            "description": "Answers 'what's for dinner?', 'what can we make tonight?' by filtering the family's OWN meals against today's actual schedule — the time at home, whether anyone eats in the car, and who's allergic to what. Use whenever someone asks what to eat. Does NOT invent recipes and does NOT know what food is in the house.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD."}
                },
                "required": []
            }
        },
        {
            "name": "add_meal_to_repertoire",
            "description": "Adds one of the family's regular meals in THEIR OWN WORDS — a bare name ('we make tacos') or a whole plate written out ('chicken, rice, beans black red or pinto, veggies, salad'). Pass their description through verbatim: a short name, cook times, portability and the components (including substitutable options like the beans) are all derived automatically. NEVER ask for cook times or ingredients, and never make them shorten it first. A plate is ONE meal, not one per component.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The family's description of the meal, verbatim — a name or a full plate."}
                },
                "required": ["name"]
            }
        },
        {
            "name": "add_meal_ingredients_to_list",
            "description": "Puts what a meal needs onto the shopping list ('add what we need for tacos', 'put spaghetti ingredients on the list'). Only fresh things are added — staples the family always has are skipped.",
            "parameters": {
                "type": "object",
                "properties": {
                    "meal_name": {"type": "string", "description": "Which meal from the repertoire."},
                    "list_name": {"type": "string", "description": "Which list or store; omit for the default list."}
                },
                "required": ["meal_name"]
            }
        },
        {
            "name": "get_tonights_plate",
            "description": "Answers what's for dinner / what's the plan tonight with the actual plate - the entree, the sides and any dessert - composed against today's schedule. Prefer this over suggest_dinner.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Which day: today (default), tomorrow, a weekday name, or YYYY-MM-DD."}
                },
                "required": []
            }
        },
        {
            "name": "set_meal_rule",
            "description": "Records how this household EATS, as opposed to what it eats: we only eat meat about once a week, takeout is occasional, we cook one kind of beans at a time and eat it two or three days before making the next. Use kind=frequency_cap with max_servings and window_days for how often, or kind=batch_cycle with dwell_days for cook-a-batch-then-rotate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "The rule in the family own words, e.g. meat about once a week."},
                    "kind": {"type": "string", "enum": ["frequency_cap", "batch_cycle"], "description": "frequency_cap for how often; batch_cycle for cook one, eat it a few days, then the next."},
                    "tags": {"type": "string", "description": "Comma separated dish tags it applies to, e.g. meat or beans."},
                    "dish_names": {"type": "string", "description": "Comma separated specific dishes, when tags will not do."},
                    "takeout": {"type": "boolean", "description": "true when the rule is about takeout or delivery."},
                    "max_servings": {"type": "number", "description": "How many times, for frequency_cap."},
                    "window_days": {"type": "number", "description": "Per how many days, for frequency_cap (7 = a week)."},
                    "dwell_days": {"type": "number", "description": "How many days one batch lasts, for batch_cycle."},
                    "except_dishes": {"type": "string", "description": "Comma separated dishes the rule should NOT cover, e.g. baked beans when the beans tag catches too much."}
                },
                "required": ["description"]
            }
        },
        {
            "name": "get_meal_rules",
            "description": "Lists the household meal rules (what rules do you have for our meals, how often do we eat meat).",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "plan_specific_dinner",
            "description": "Sets a specific dinner on a specific date and LOCKS it so the proposal engine never changes it: steak on Monday for Mom's birthday, Grandma is bringing dinner Tuesday, we are having the lasagna on the 14th. Dish names are optional - omit them when someone else is providing the food.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Which day: tomorrow, Monday, or YYYY-MM-DD."},
                    "dish_names": {"type": "string", "description": "Comma separated dishes, e.g. steak, salad. Omit if nobody here is cooking."},
                    "note": {"type": "string", "description": "Why, e.g. Mom's birthday or Grandma is bringing dinner."}
                },
                "required": ["target_date"]
            }
        },
        {
            "name": "unlock_dinner",
            "description": "Releases a locked night back to the proposal engine (never mind about Monday, unlock Tuesday).",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Which day."}
                },
                "required": ["target_date"]
            }
        },
        {
            "name": "pair_dishes",
            "description": "Records that dishes always come together (brisket always comes with beans and fries, pizza always with salad). Directed: the partners stay free to appear beside other things. Set exclusive=true for the reverse - this dish is ONLY ever proposed alongside those partners.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "The dish that brings the others, e.g. brisket."},
                    "partner_names": {"type": "string", "description": "Comma separated dishes that come with it, e.g. beans, fries."},
                    "exclusive": {"type": "boolean", "description": "true for 'X is only ever served with Y'."}
                },
                "required": ["dish_name", "partner_names"]
            }
        },
        {
            "name": "add_occasion",
            "description": "Records a holiday, birthday, party or get-together so the app can carry it: Thanksgiving is on the 26th and my parents are here from the 25th to the 29th, Ellie's birthday party is on the 14th. The window is when guests are around and prep happens - it makes holiday dishes available without putting them on any plate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "What to call it, e.g. Thanksgiving 2026."},
                    "anchor_date": {"type": "string", "description": "The day itself, e.g. 2026-11-26 or the 26th."},
                    "kind": {"type": "string", "description": "thanksgiving|christmas|easter|birthday|party|gathering"},
                    "window_start": {"type": "string", "description": "YYYY-MM-DD when guests arrive / prep starts. Optional."},
                    "window_end": {"type": "string", "description": "YYYY-MM-DD when it is over. Optional."},
                    "dish_tags": {"type": "string", "description": "Comma separated repertoire tags this occasion brings out, e.g. thanksgiving."}
                },
                "required": ["title", "anchor_date"]
            }
        },
        {
            "name": "get_occasion",
            "description": "Reads the state of a holiday or party: what's the state of Thanksgiving, who is coming to the party, what still needs doing for Ellie's birthday. Reports guests, headcount, lists and outstanding errands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion_name": {"type": "string", "description": "Which one; omit for the next one coming up."}
                },
                "required": []
            }
        },
        {
            "name": "get_occasion_insights",
            "description": "The judgement calls around a holiday or party that a checklist cannot make: who is carrying all the work, what is still undecided and what waiting will cost, the clearest day in the schedule to get something done, deadlines that fall out of the food itself (a bird that needs thawing pushes back the buy date), and clashes between the cooking window and who is out driving. Use for how is Thanksgiving looking, is anything going to go wrong, who is doing all the work.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion_name": {"type": "string", "description": "Which one; omit for the next one coming up."}
                },
                "required": []
            }
        },
        {
            "name": "get_occasion_gaps",
            "description": "Says what is still MISSING for a holiday or party - what still needs doing for Thanksgiving, am I forgetting anything for the party. This is a diff against the usual shape of that kind of occasion and against last year's, ordered by how little time is left. Use it whenever someone asks whether they have forgotten something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion_name": {"type": "string", "description": "Which one; omit for the next one coming up."}
                },
                "required": []
            }
        },
        {
            "name": "set_occasion_attendance",
            "description": "Records whether someone in the FAMILY is coming to an occasion: Grandad is not coming to Thanksgiving this year, Sarah is away for the party, actually Marta is joining us for Christmas. Everyone in the household is assumed in except helpers, and this is how that is corrected either way. For people outside the family use add_occasion_guests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion_name": {"type": "string", "description": "Which occasion."},
                    "who": {"type": "string", "description": "A family member's name."},
                    "coming": {"type": "boolean", "description": "true if they are coming, false if not."}
                },
                "required": ["occasion_name", "who", "coming"]
            }
        },
        {
            "name": "add_occasion_guests",
            "description": "Adds people to an occasion's guest list: the Wilsons are coming and there are four of them, Grandma is coming and she cannot have shellfish. Allergies here bind exactly like a family member's - the meal planner stops proposing them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion_name": {"type": "string", "description": "Which occasion."},
                    "who": {"type": "string", "description": "A name or a household, e.g. the Wilsons."},
                    "headcount": {"type": "integer", "description": "How many people that is. Default 1."},
                    "cannot_eat": {"type": "string", "description": "Comma separated allergies/avoidances."}
                },
                "required": ["occasion_name", "who"]
            }
        },
        {
            "name": "source_for_occasion",
            "description": "Turns what an occasion needs into a real shopping list, scaled to the headcount: I need party favours for a shark party, we need decorations and paper plates. The list belongs to the occasion and goes to a cart from the Shopping page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion_name": {"type": "string", "description": "Which occasion."},
                    "needed": {"type": "string", "description": "What they need, in their words."}
                },
                "required": ["occasion_name", "needed"]
            }
        },
        {
            "name": "get_run_sheet",
            "description": "Works out when to start cooking and what goes on when, counting back from when the family eats: when do I need to start on Thursday, what time does the turkey go in, how early do I have to be up for this. Accounts for one oven at two temperatures and for how many people are cooking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "The night, e.g. today, Saturday, 2026-11-26."},
                    "serve_at": {"type": "string", "description": "Optional HH:MM to eat at; omit to use the family's own sitting."}
                },
                "required": []
            }
        },
        {
            "name": "set_hosting",
            "description": "Records how many people are eating on a given night and how many are cooking: we are having twelve people on Saturday, four of us are cooking Thursday, it is just us again on the 20th. Headcount multiplies the hands-on work and cooks divide it, so this is what turns a plate into a realistic evening. Pass serving_for=0 to go back to an ordinary night.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "The night, e.g. Saturday, tomorrow, or 2026-11-26."},
                    "serving_for": {"type": "integer", "description": "Whole headcount including the family. 0 clears it."},
                    "cooks": {"type": "integer", "description": "How many people are cooking. Omit or 0 to leave as is."}
                },
                "required": ["target_date", "serving_for"]
            }
        },
        {
            "name": "set_dish_scope",
            "description": "Marks a dish as holiday and party food rather than everyday food, so it stops being suggested on ordinary nights: turkey is only for holidays, we only make deviled eggs for parties, the trifle is a Christmas thing. Set occasion_only=false to put it back in the everyday rotation. This changes what gets SUGGESTED - the dish stays pickable by hand and its leftovers still count.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "Which dish, e.g. turkey."},
                    "occasion_only": {"type": "boolean", "description": "true for holiday/party only (the default), false to return it to everyday."}
                },
                "required": ["dish_name"]
            }
        },
        {
            "name": "set_dish_categories",
            "description": "Corrects what a dish IS on the plate, using the family's own categories: black beans are a protein not just a starch, spaghetti and meat sauce is a whole meal on its own, the chili serves eight. A dish may belong to several categories - it then fills whichever one the plate still needs, never two at once. Use this instead of re-adding the dish when the classification came out wrong.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "Which dish, e.g. black beans."},
                    "categories": {"type": "string", "description": "Comma-separated category names, in the family's own words, e.g. 'protein, starches/carbs'."},
                    "whole_meal": {"type": "boolean", "description": "true if it is a whole dinner on its own and nothing is served beside it."},
                    "serves": {"type": "integer", "description": "How many people it feeds."},
                    "whole_units": {"type": "boolean", "description": "true if it is made in indivisible whole units - a tray of lasagna, a cake, a sheet pan - so feeding more people means making another whole one."}
                },
                "required": ["dish_name"]
            }
        },
        {
            "name": "unpair_dishes",
            "description": "Removes a pairing (brisket does not always come with fries anymore).",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "Which dish."},
                    "partner_name": {"type": "string", "description": "Which partner; omit to clear all of that dish's pairings."}
                },
                "required": ["dish_name"]
            }
        },
        {
            "name": "set_dish_prep",
            "description": "Records prep that happens OUTSIDE the cook window and sets the reminder for it: we soak the rice the night before, the beans soak overnight, the chicken marinates an hour first, take the mince out in the morning. Use whenever someone describes something done ahead of cooking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "Which dish, e.g. rice or chicken."},
                    "action": {"type": "string", "description": "The verb: soak, marinate, thaw, take out of the freezer."},
                    "when": {"type": "string", "enum": ["night_before", "hours_before", "morning_of"], "description": "night_before for overnight soaking, hours_before with hours for a marinade, morning_of for a thaw."},
                    "hours": {"type": "number", "description": "How many hours before dinner, when using hours_before."}
                },
                "required": ["dish_name", "action"]
            }
        },
        {
            "name": "clear_dish_prep",
            "description": "Removes prep from a dish (we do not soak the rice anymore, stop reminding me to marinate the chicken).",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "Which dish."},
                    "action": {"type": "string", "description": "Which step; omit to clear all prep for that dish."}
                },
                "required": ["dish_name"]
            }
        },
        {
            "name": "get_prep_ahead",
            "description": "Answers is there anything I need to do tonight / do I need to soak anything / anything to prep for tomorrow. Lists work due outside the cook window for tonight and tomorrow.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "get_shopping_trip",
            "description": "Answers when are we going shopping / when is the grocery run. Returns the SCHEDULED trip if the solver has placed it, plus how many things are waiting on that list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "list_name": {"type": "string", "description": "Which list or store; omit for the default list."}
                },
                "required": []
            }
        },
        {
            "name": "schedule_shopping_trip",
            "description": "Creates a recurring shopping trip for a list (schedule a grocery run, we need a shopping trip, add a weekly Costco run). The solver then fits it into the week. Use when there is no trip yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "store": {"type": "string", "description": "Where they shop, e.g. Kroger on Main St."},
                    "list_name": {"type": "string", "description": "Which list; omit for the default list."},
                    "weekly": {"type": "boolean", "description": "true (default) for a standing weekly run, false for a one-off."}
                },
                "required": []
            }
        },
        {
            "name": "get_week_dinners",
            "description": "Answers what are we eating this week / what is the meal plan / what do I need to buy for. Returns every night in the span the next grocery run has to cover, and which nights are already pinned.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "approve_week_dinners",
            "description": "The family says the week looks good (that works, looks good, approve the plan, plan the week). Pins every night and puts the whole span's fresh ingredients on the shopping list in one go. Only for approving the WHOLE week - use change_tonights_plate to alter a single night.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "change_tonights_plate",
            "description": "Adds or drops ONE dish for ONE evening (we have got corn too, no salad tonight, add rice, skip the potatoes). Changes only that evening's plate - the family's list of what they cook is untouched. Use this for anything about what is being eaten TODAY.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "Which dish, e.g. corn or salad."},
                    "action": {"type": "string", "enum": ["add", "remove"], "description": "add (default) or remove."},
                    "target_date": {"type": "string", "description": "Which day: today (default), tomorrow, a weekday name, or YYYY-MM-DD."}
                },
                "required": ["dish_name"]
            }
        },
        {
            "name": "add_dishes",
            "description": "Adds things the family COOKS to their repertoire, in their own words (we make roast chicken, rice, and beans - black, red or pinto). Every alternative becomes its own dish, and each is typed as a whole meal, an entree, a side or a dessert so plates can be built from them. Use this for what they cook in general, NOT for what is being eaten tonight.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Their description, verbatim."}
                },
                "required": ["description"]
            }
        },
        {
            "name": "refine_meal_dish",
            "description": "Answers a question about a vague part of a meal ('the potatoes are russet, roasted', 'we mash them'). Makes that dish's cook time and shopping line accurate. Use whenever the family clarifies WHICH kind of something or HOW it is cooked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {"type": "string", "description": "The vague dish, e.g. 'potatoes'."},
                    "detail": {"type": "string", "description": "What they said, e.g. 'russet, roasted'."}
                },
                "required": ["dish_name", "detail"]
            }
        },
        {
            "name": "mark_leftovers",
            "description": "Records that food is ALREADY MADE for a day ('we're having leftovers tonight', 'we're finishing Sunday's chili', 'the rice is already made'). This stops the app holding cook time for work nobody is going to do, and keeps those ingredients off the shopping list. Use `parts` when only some of a meal is left over.",
            "parameters": {
                "type": "object",
                "properties": {
                    "what": {"type": "string", "description": "What the leftovers are, e.g. 'chili'. Matches a meal in the repertoire when it can; free text otherwise. Omit for plain 'we have leftovers'."},
                    "target_date": {"type": "string", "description": "Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD."},
                    "parts": {"type": "string", "description": "Only if PART of a meal is left over, e.g. 'rice' or 'rice and beans'. Name the dishes; each one recognised subtracts its own real cook time. Omit when the whole meal is leftovers."}
                },
                "required": []
            }
        },
        {
            "name": "clear_leftovers",
            "description": "Undoes an already-made note ('actually we're cooking tonight', 'the rice isn't made after all', 'the leftovers are gone'). Name a dish in `what` to un-mark just that one; omit it to clear the whole day.",
            "parameters": {
                "type": "object",
                "properties": {
                    "what": {"type": "string", "description": "A single dish to un-mark, e.g. 'rice'. Omit to clear everything marked for that day."},
                    "target_date": {"type": "string", "description": "Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD."}
                },
                "required": []
            }
        },
        {
            "name": "mark_meal_served",
            "description": "Records that the family had a meal ('we had tacos tonight', 'we made chili'). Keeps the rotation from suggesting the same thing twice in a week. Adds the meal to the repertoire if it isn't there yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "meal_name": {"type": "string", "description": "What they ate."}
                },
                "required": ["meal_name"]
            }
        },
        {
            "name": "remove_shopping_item_by_name",
            "description": "Removes something from the shopping list entirely because it is no longer wanted ('take cilantro off the list', 'we don't need bread after all'). This is NOT for items that were bought — use check_off_shopping_item for those.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "The item to remove."},
                    "list_name": {"type": "string", "description": "Which list or store. Omit for the default list."}
                },
                "required": ["item_name"]
            }
        },
        {
            "name": "propose_family_action",
            "description": "Propose a schedule- or calendar-CHANGING action for a parent to approve with one tap in the chat, instead of doing it silently. Use this in the family chat whenever the request would reassign or clear a driver, add/remove a routing or priority rule (e.g. mark a driver unavailable), add/update/remove an errand, or add a calendar event. ALSO the correct tool when a CHILD reports logistics news ('practice moved to 5', 'I need $12 by Friday', 'the game got cancelled') — the card reaches their parents for approval. Do NOT use it for questions, reading the schedule, sending messages, or chore claims — handle those directly.",
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
    "manage_car",
    # Presence & Status P1: set/read family status days from the admin chat.
    # Not schedule-mutating (slice 1 never touches the solver).
    "set_household_status", "get_household_status",
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
    "manage_car",
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
    try:
        # K2 on-the-way push to child passengers — same hook as the PWA's
        # Start Drive button (lazy main import, same pattern as the chat
        # fan-out; absent/failing in tests -> skipped silently).
        import main as _main
        _main._notify_kids_ride_started(ev["id"])
    except Exception:
        pass
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
