import json
import uuid
import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

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

    # Speech-tolerant, because the name in a voice command has been through
    # speech-to-text. The old match was `name in driver.name` plus a lookup of
    # a "hashtag" key that does not exist on a Driver (the field is `hashtags`,
    # a list), so it was substring-only in practice — and a substring never
    # finds Celma from "Selma".
    target_driver, known = _match_person(driver_name, get_all_drivers())
    if not target_driver:
        # Name the roster. Without it the model has nothing to correct against
        # and simply retries the same misheard name.
        return {"status": "error",
                "message": f"Could not find a driver matching '{driver_name}'. "
                           f"The drivers are: {', '.join(known)}."}
        
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

def decide_optional_event(event_name: str, target_date: str, decision: str,
                          member_id: str = None) -> Dict[str, Any]:
    """
    Optional events, phase 2: record the family's per-occurrence choice for an
    event flagged optional — 'attend' (a firm commitment now, full solver
    weight), 'skip' (out of today's plan, nobody scheduled or chased), or
    'clear' (back to goes-if-it-fits).
    """
    from services import optional_events
    return optional_events.decide_by_title(event_name, target_date, decision,
                                           decided_by=member_id)


def set_event_optional(event_name: str, target_date: str, optional: bool = True,
                       scope: str = 'series') -> Dict[str, Any]:
    """
    Flags an event optional (or firm again) in its event config — the same
    flag as the Optional checkbox on the event modals. scope 'series' (the
    default) covers every occurrence of a recurring event; 'instance' only
    the one on target_date.
    """
    from services import optional_events
    return optional_events.set_optional_flag(event_name, target_date,
                                             bool(optional), scope or 'series')


def cancel_event(event_name: str, target_date: str = 'today', reason: str = '',
                 acting_member: dict = None) -> Dict[str, Any]:
    """
    Cancels ONE occurrence of an event: recorded with the reason, mirrored to
    Google (CANCELED prefix + Free), driver and kids pushed. Parent/adult only.
    """
    from services import cancellations
    return cancellations.cancel_by_title(event_name, target_date, reason=reason,
                                         acting_member=acting_member)


def restore_event(event_name: str, target_date: str = 'today',
                  acting_member: dict = None) -> Dict[str, Any]:
    """
    Un-cancels an occurrence: the record stays as history, the Google title
    and availability are restored, everyone is told it is back on.
    """
    from services import cancellations
    return cancellations.cancel_by_title(event_name, target_date,
                                         acting_member=acting_member,
                                         restore=True)


def group_events_ride_together(event_names, target_date: str = 'today',
                               acting_member: dict = None) -> Dict[str, Any]:
    """
    Groups one day's event occurrences to ride together: one driver, never a
    conflict, one trip. That day only -- never a rule. Parent/adult only.
    """
    from services import ride_groups
    return ride_groups.group_by_titles(event_names, target_date,
                                       acting_member=acting_member)


def ungroup_event(event_name: str, target_date: str = 'today',
                  acting_member: dict = None) -> Dict[str, Any]:
    """Takes one occurrence out of its ride-together group."""
    from services import ride_groups
    return ride_groups.ungroup_by_title(event_name, target_date,
                                        acting_member=acting_member)


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


# Whole features a household can switch off (services/household_features.py).
# Every agent tool that touches one answers with the switch instead of acting,
# in BOTH stacks -- the v1 handlers delegate to these functions.
CRITTERS_OFF = {"status": "error",
                "message": "Critters are switched off for this family right now. "
                           "A parent can turn them back on from the Chores page."}
REWARDS_OFF = {"status": "error",
               "message": "Rewards and family goals are switched off for this family "
                          "right now. Points still count; a parent can turn rewards "
                          "back on from the Chores page."}


def _critters_off() -> bool:
    from services import household_features
    return not household_features.critters_enabled()


def _rewards_off() -> bool:
    from services import household_features
    return not household_features.rewards_enabled()


def challenge_pet_battle(challenger_name: str, opponent_name: str) -> Dict[str, Any]:
    """Ask somebody for a pet battle, on behalf of a child who said so out loud.

    ASKING IS ALL IT DOES. The agent cannot accept on the other child's
    behalf, and no amount of asking resolves anything -- consent belongs to
    the person being challenged, and handing that to an assistant would make
    it possible to be dragged into a fight by someone talking to a speaker in
    another room."""
    if _critters_off():
        return dict(CRITTERS_OFF)
    from services import storage
    me = _find_member_fuzzy(challenger_name)
    them = _find_member_fuzzy(opponent_name)
    if not me:
        return {"message": f"I don't know who {challenger_name} is."}
    if not them:
        return {"message": f"I don't know who {opponent_name} is."}
    res = storage.create_pet_challenge(me['id'], them['id'])
    if res.get('error'):
        return {"message": res['error']}
    return {"message": f"Asked {them.get('name')} for a battle. "
                       f"It's up to them now — and it'll be level-matched."}


def award_pet_xp(member_name: str, amount: int) -> Dict[str, Any]:
    """Hand somebody pet experience out loud -- the xp twin of adjust_points.

    Deliberately cannot reach the POINTS ledger: xp buys nothing outside the
    game, so this is a safe thing to say to a speaker, and points are not."""
    if _critters_off():
        return dict(CRITTERS_OFF)
    from services import storage
    m = _find_member_fuzzy(member_name)
    if not m:
        return {"message": f"I don't know who {member_name} is."}
    res = storage.adjust_pet_xp(m['id'], int(amount or 0))
    if res.get('error'):
        return {"message": res['error']}
    verb = "gave" if int(amount or 0) > 0 else "took back"
    return {"message": f"{verb} {abs(int(amount))} pet XP "
                       f"{'to' if int(amount) > 0 else 'from'} {m.get('name')}. "
                       f"They're level {res['level']} with {res['balance']} to spend."}


def get_pet_status(member_name: str = None) -> Dict[str, Any]:
    """How somebody's critter is doing. Deliberately reports level, element
    and XP and NOT a win-loss record: there isn't one, and inventing one in a
    spoken answer would be the ladder this arc refuses to build."""
    if _critters_off():
        return dict(CRITTERS_OFF)
    from services import storage
    from services import pet_catalog
    lines = []
    members = ([_find_member_fuzzy(member_name)] if member_name
               else storage.get_all_members())
    for m in [x for x in members if x]:
        pets = storage.get_pets(m['id'])
        if not pets:
            continue
        prog = storage.pet_level_progress(m['id'])
        for pet in pets:
            t = pet_catalog.get(pet.get('type')) or {}
            lines.append(f"{m.get('name')}'s {pet.get('name')} is a level "
                         f"{prog['level']} {t.get('label', '')} critter"
                         + (f", {prog['need']} XP from the next level"
                            if not prog.get('max') else ""))
    if not lines:
        return {"message": "Nobody has hatched a critter yet."}
    return {"message": ". ".join(lines) + "."}


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


def _fold_name(raw: str) -> str:
    """A name reduced to roughly how it SOUNDS, for comparing against speech.

    Most requests reach the agent through speech-to-text, and the names in this
    house are not in Whisper's head: it hears Celma as "Selma" and Vovo as
    "Volvo". Those are not typos and no amount of substring matching finds
    them — "selma" is not inside "celma".

    This is deliberately a handful of rules and not a metaphone: soft c -> s
    (the Celma case), ph -> f, hard c/ck -> k, z -> s, and doubles collapsed.
    Anything it misses is caught by the edit-distance tier in _match_person,
    which is what covers a whole inserted syllable like the l in Volvo."""
    import re
    import unicodedata
    s = unicodedata.normalize('NFKD', (raw or '').strip().lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^a-z]', '', s)
    s = s.replace('ph', 'f').replace('ck', 'k')
    s = re.sub(r'c(?=[eiy])', 's', s)        # Celma -> selma, Cindy -> sindy
    s = s.replace('c', 'k').replace('z', 's')
    return re.sub(r'(.)\1+', r'\1', s)       # Aaron -> aron


def _match_person(query: str, people: list):
    """Resolve one spoken or typed name against a roster.

    Returns (person, candidate_names). A miss returns (None, every name we
    know) so the caller can put the real roster in its error — the model then
    retries with a name that exists instead of guessing again at the one it
    misheard.

    Tiers, each requiring a UNIQUE winner before it is trusted: exact, then an
    explicit hashtag (the hand path — add "#selma" to Celma and the mishearing
    is pinned for good), then substring/first name, then the sound-folded form,
    and only last a close-spelling score. That final tier demands both a high
    ratio AND a clear margin over the runner-up, because this family contains
    Grandpa and Grandma: 0.857 similar to each other, and a lone threshold
    would cheerfully hand a wrong grandparent the car keys."""
    import difflib
    q = (query or '').strip().lower().lstrip('#')
    people = [p for p in (people or []) if (p.get('name') or '').strip()]
    if not q or not people:
        return None, [p.get('name') for p in people]

    def nm(p):
        return (p.get('name') or '').strip().lower()

    def tags(p):
        raw = p.get('hashtags') or p.get('hashtag') or []
        if isinstance(raw, str):
            raw = [raw]
        return {str(t).lstrip('#').strip().lower() for t in raw if t}

    for candidates in (
        [p for p in people if nm(p) == q],
        [p for p in people if q in tags(p)],
        [p for p in people if q in nm(p) or nm(p).split(' ')[0] == q],
        [p for p in people if _fold_name(nm(p)) == _fold_name(q)],
    ):
        if len(candidates) == 1:
            return candidates[0], []

    fq = _fold_name(q)
    scored = sorted(((difflib.SequenceMatcher(None, fq, _fold_name(nm(p))).ratio(), p)
                     for p in people), key=lambda t: t[0], reverse=True)
    if scored and scored[0][0] >= 0.8 and (
            len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.06):
        return scored[0][1], []
    return None, [p.get('name') for p in people]


def _find_member_fuzzy(name: str):
    if not name:
        return None
    from services.storage import get_all_members
    member, _ = _match_person(
        name, [m for m in get_all_members() if not m.get('system')])
    return member


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


def _post_chat_message(channel: dict, sender: dict, body: str, card: dict = None,
                       context: dict = None) -> dict:
    """Store a chat message and fire the same SSE + push fan-out as the
    /api/channels POST endpoint. main is lazily imported (it is the running
    app module); in tests it is absent and fan-out is skipped silently.
    An optional card renders as an interactive element (e.g. an action proposal)."""
    from models.schemas import ChatMessage
    from services import storage
    message = ChatMessage(channel_id=channel['id'], sender_member_id=sender['id'],
                          body=body, card=card, context=context).model_dump()
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


def make_request(body: str, to_member: str = None, kind: str = None,
                 about: str = None, acting_member: dict = None,
                 sender_driver_id: str = None) -> Dict[str, Any]:
    """Raise an ask. This is how a kid says "can you get me at 3 instead of 4"
    and how an adult says "can you take Thursday" — the same rails, because
    the state machine is identical."""
    from services import requests as _req, storage
    asker, err = _resolve_actor(sender_driver_id, None)
    if not asker:
        asker = acting_member
    if not asker:
        return {"status": "error",
                "message": "I need to know who's asking — tell me your name."}
    text = (body or '').strip()
    if not text:
        return {"status": "error", "message": "What do you want to ask for?"}
    target = None
    if to_member:
        target = _find_member_fuzzy(to_member)
        if not target:
            return {"status": "error",
                    "message": f"I couldn't find '{to_member}'. Family members: {_member_names()}."}
    k = (kind or 'other').strip().lower()
    if k not in _req.KINDS:
        k = 'other'
    # A named subject makes accepting DO the thing rather than just agree to
    # it. Tasks resolve by title; a drive resolves by event title today.
    subject_ref, subject_label = None, (about or '').strip()
    if subject_label:
        task, _rows = _match_task(subject_label)
        if task:
            subject_ref, subject_label, k = task['id'], task['title'], 'take_task'
    row = _req.create(asker['id'], text, kind=k,
                      to_member_id=(target or {}).get('id'),
                      subject_ref=subject_ref, subject_label=subject_label)
    if row.get('status') == 'error':      # stage-gated (load arc A4)
        return row
    who = target.get('name') if target else "everyone who could say yes"
    return {"status": "success",
            "message": f"Asked {who}: “{text}”. I'll tell you the moment there's an answer."}


def get_requests(acting_member: dict = None, sender_driver_id: str = None) -> Dict[str, Any]:
    from services import requests as _req
    who, _err = _resolve_actor(sender_driver_id, None)
    who = who or acting_member
    if not who:
        return {"status": "error", "message": "Who am I checking for?"}
    data = _req.summary_for(who['id'])
    lines = []
    for r in data['waiting_on_me']:
        lines.append(f"{r['from']} is asking: “{r['body']}”")
    for r in data['mine']:
        lines.append(f"You asked {r['to']}: “{r['body']}” — no answer yet")
    if not lines:
        return {"status": "success", "message": "Nothing waiting either way."}
    return {"status": "success", "message": "\n".join(lines)}


def answer_request(accept: bool, which: str = None, reason: str = None,
                   acting_member: dict = None, sender_driver_id: str = None) -> Dict[str, Any]:
    from services import requests as _req
    who, _err = _resolve_actor(sender_driver_id, None)
    who = who or acting_member
    if not who:
        return {"status": "error", "message": "Who's answering?"}
    open_for_me = [r for r in _req.summary_for(who['id'])['waiting_on_me']]
    if not open_for_me:
        return {"status": "success", "message": "Nothing is waiting on you."}
    target = None
    if which:
        q = which.strip().lower()
        hits = [r for r in open_for_me
                if q in (r['body'] or '').lower() or q in (r['from'] or '').lower()]
        if len(hits) == 1:
            target = hits[0]
    elif len(open_for_me) == 1:
        target = open_for_me[0]
    if not target:
        asks = "; ".join(f"{r['from']}: “{r['body']}”" for r in open_for_me[:5])
        return {"status": "error",
                "message": f"Which one? {asks}"}
    res = _req.decide(target['id'], bool(accept), who['id'], reason or "")
    return {"status": res.get('status', 'success'), "message": res.get('message'),
            "schedule_dirty": res.get('schedule_dirty')}


def _task_due_date(when: str):
    """A spoken deadline into YYYY-MM-DD, or None. None is a real answer —
    'sort the garage' is work with no date, and inventing one would put a
    false deadline in front of the family."""
    if not (when or '').strip():
        return None
    try:
        return _parse_fuzzy_date(when).isoformat()
    except Exception:
        return None


def add_household_task(title: str, due: str = None, assign_to: str = None,
                       notes: str = None, recurrence: str = None,
                       category: str = None, acting_member: dict = None) -> Dict[str, Any]:
    """Work with a deadline and no destination. If it needs a drive it is an
    errand; this is for the permission slip, the phone call, the renewal."""
    from models.schemas import HouseholdTask
    from services import storage
    title = (title or '').strip()
    if not title:
        return {"status": "error", "message": "What is the task?"}
    owner = None
    if assign_to:
        owner = _find_member_fuzzy(assign_to)
        if not owner:
            return {"status": "error",
                    "message": f"I couldn't find '{assign_to}'. Family members: {_member_names()}."}
        # Stage gate (load arc A4): the same door the API refuses at, so
        # neither agent stack can hand a Sprout the passport renewal.
        from services import stages
        block = stages.refuse_task_assignment(owner)
        if block:
            return {"status": "error", "message": block}
    rec = (recurrence or 'none').strip().lower()
    if rec not in ('none', 'daily', 'weekly', 'monthly', 'yearly'):
        rec = 'none'
    task = HouseholdTask(
        title=title, due_date=_task_due_date(due), notes=(notes or '').strip(),
        assigned_to=(owner or {}).get('id'), recurrence=rec,
        category=(category or 'general').strip().lower() or 'general',
        created_by=(acting_member or {}).get('id'), source='agent').model_dump()
    storage.add_household_task(task)
    who = f" for {owner['name']}" if owner else ""
    when = f", due {task['due_date']}" if task['due_date'] else ""
    every = f", every {rec}" if rec != 'none' else ""
    return {"status": "success",
            "message": f"Added \"{title}\"{who}{when}{every} to the household list."}


def get_household_tasks(assigned_to: str = None, unassigned_only: bool = False) -> Dict[str, Any]:
    import datetime
    from services import storage
    owner = _find_member_fuzzy(assigned_to) if assigned_to else None
    if assigned_to and not owner:
        return {"status": "error",
                "message": f"I couldn't find '{assigned_to}'. Family members: {_member_names()}."}
    rows = storage.get_household_tasks(assigned_to=(owner or {}).get('id'),
                                       unassigned_only=unassigned_only)
    if not rows:
        if unassigned_only:
            return {"status": "success", "message": "Nothing is sitting unclaimed."}
        return {"status": "success",
                "message": f"Nothing on {owner['name']}'s list." if owner
                           else "The household list is clear."}
    names = {m['id']: m.get('name') for m in storage.get_all_members(include_archived=True)}
    today = datetime.date.today().isoformat()
    lines = []
    for t in rows[:15]:
        bits = [t.get('title') or 'Task']
        if t.get('due_date'):
            bits.append("past due" if t['due_date'] < today else f"due {t['due_date']}")
        holder = names.get(t.get('assigned_to') or '')
        bits.append(holder if holder else "nobody yet")
        lines.append(" — ".join(bits))
    head = (f"{owner['name']}'s list:" if owner
            else ("Waiting for somebody to take it:" if unassigned_only
                  else "The household list:"))
    return {"status": "success", "message": head + "\n" + "\n".join(lines)}


def _match_task(title: str):
    from services import storage
    q = (title or '').strip().lower()
    rows = storage.get_household_tasks()
    if not q:
        return None, rows
    exact = [t for t in rows if (t.get('title') or '').lower() == q]
    if len(exact) == 1:
        return exact[0], rows
    part = [t for t in rows if q in (t.get('title') or '').lower()]
    if len(part) == 1:
        return part[0], rows
    return None, rows


def complete_household_task(title: str, acting_member: dict = None) -> Dict[str, Any]:
    from services import storage
    task, rows = _match_task(title)
    if not task:
        open_titles = ', '.join(t.get('title') or '?' for t in rows[:8]) or 'nothing'
        return {"status": "error",
                "message": f"I couldn't pin down '{title}'. Open: {open_titles}."}
    row = storage.complete_household_task(task['id'], True,
                                          (acting_member or {}).get('id'))
    msg = f"Done: {task.get('title')}."
    if row and row.get('next_due_date'):
        msg += f" The next one is due {row['next_due_date']}."
    return {"status": "success", "message": msg}


def claim_household_task(title: str, member_name: str = None,
                         acting_member: dict = None) -> Dict[str, Any]:
    """Put a name on work the household owed. This is the delegation path —
    and the reason `assigned_to` is optional in the first place."""
    from services import storage
    owner, err = (_find_member_fuzzy(member_name), None) if member_name else (acting_member, None)
    # Outside hands hold housework too ("get the Kellys' girl to do the
    # dishes"), so a name that is nobody in the family is tried against the
    # contacts before it is called unfindable. The hand path offers both in
    # one dropdown; the agent has to be able to say both or it is the weaker
    # of the two, which is the same parity rule in the other direction.
    holder_id = holder_name = None
    if owner:
        holder_id, holder_name = owner['id'], owner.get('name')
    elif member_name:
        from services import assist as _assist
        contact = _find_assist_contact(member_name)
        if contact:
            holder_id = _assist.make_id(contact['id'])
            holder_name = contact.get('name')
    if not holder_id:
        if member_name:
            return {"status": "error",
                    "message": f"I couldn't find '{member_name}'. Family members: {_member_names()}."}
        return {"status": "error",
                "message": "Who should take it? Tell me a name."}
    if owner:
        from services import stages
        block = stages.refuse_task_assignment(owner)
        if block:
            return {"status": "error", "message": block}
    task, rows = _match_task(title)
    if not task:
        open_titles = ', '.join(t.get('title') or '?' for t in rows[:8]) or 'nothing'
        return {"status": "error",
                "message": f"I couldn't pin down '{title}'. Open: {open_titles}."}
    storage.update_household_task(task['id'], {'assigned_to': holder_id})
    return {"status": "success",
            "message": f"{holder_name} has {task.get('title')}."}


def get_household_load(days: int = 30) -> Dict[str, Any]:
    """Who is carrying what. STATES, never scores — the occasions
    `_load_balance` voice. No percentages, no leaderboard, no chart: adults
    need division of labour, not gamification, and a fairness chart between
    two spouses is a fight generator."""
    try:
        import main as _main
        data = _main.household_load(days=days)
    except Exception as e:
        return {"status": "error", "message": f"I couldn't work that out ({e})."}
    parts = []
    for r in data.get('household', []):
        if r.get('total'):
            parts.append(f"{r['name']}: {r['total']}")
    if not parts:
        return {"status": "success",
                "message": f"Nothing logged in the last {days} days."}
    msg = f"Last {days} days — " + ", ".join(parts) + "."
    if data.get('line'):
        msg += " " + data['line']
    helping = [f"{r['name']}: {r['total']}" for r in data.get('assisting', []) if r.get('total')]
    if helping:
        # Named separately on purpose: help covers work, it does not carry
        # the household's share of it.
        msg += " Helping hands (not counted in the split) — " + ", ".join(helping) + "."
    return {"status": "success", "message": msg}


def _find_assist_contact(name: str):
    """Match a spoken name against the assist contacts, on BOTH the name and
    the label the family actually says. Nobody in this house says "Sarah
    Whitfield" out loud; they say "Emma's mom", and a matcher that only
    knows legal names would miss every real utterance."""
    import re
    from services import storage
    contacts = storage.get_assist_contacts()

    def _variants(label: str):
        """Every way a person might say a label out loud. The apostrophe is
        the one that actually bites: speech-to-text writes "emmas mom" and a
        tag of "Emma's mom" never matches it."""
        label = (label or '').strip()
        if not label:
            return []
        flat = re.sub(r"[^a-z0-9 ]", "", label.lower())          # emmas mom
        loose = re.sub(r"\s+", " ", label.lower().replace("'s", "s")).strip()
        out = {label, flat, loose}
        # Single words too ("emma"). "mom" will collide across two carpool
        # parents — which is safe, because _match_person requires a UNIQUE
        # winner in a tier and an ambiguous tag simply falls through rather
        # than handing the drive to the wrong household.
        out.update(w for w in flat.split() if len(w) > 2)
        return [v for v in out if v]

    roster = []
    for c in contacts:
        # _match_person reads `name` and `hashtags`; feeding it the relation
        # label as tags makes "Emma's mom" a first-class way to be found
        # without teaching the matcher a new field.
        entry = dict(c)
        entry['hashtags'] = _variants(c.get('relation_label'))
        roster.append(entry)
    contact, _ = _match_person(name, roster)
    return contact


def cover_with_assist(event_name: str, contact_name: str = None,
                      target_date: str = None, clear: bool = False,
                      scope: str = 'instance', leg: str = None) -> Dict[str, Any]:
    """Hand a drive to somebody outside the household, or take it back.

    Deliberately not an override: an override says "this driver, whatever the
    solver thinks"; this says "not ours at all", and the event leaves the
    optimisation entirely.

    `scope='series'` covers every occurrence — the standing arrangement
    ("Emma's mom has Tuesdays"), which until now the model could only fake by
    covering one day and reporting the season handled.
    """
    import datetime
    from services import assist as _assist, storage
    day = _parse_fuzzy_date(target_date or 'today')
    sched = storage.get_cached_schedule() or {}
    todays = []
    for ev in sched.get('events', []):
        try:
            if datetime.datetime.fromisoformat(str(ev.get('start'))).date() == day:
                todays.append(ev)
        except (ValueError, TypeError):
            continue
    if not todays:
        return {"status": "error",
                "message": f"Nothing is on the schedule for {day.strftime('%A %d %b')}."}

    q = (event_name or '').strip().lower()
    matches = [e for e in todays if q and q in (e.get('title') or '').lower()]
    leg = str(leg or '').strip().lower().replace('-', '')
    if leg in ('dropoff', 'pickup'):
        match = next((e for e in matches
                      if str(e.get('id') or '').endswith(f'_{leg}')), None)
    else:
        leg = None
        match = next((e for e in matches
                      if not _assist.split_leg(e.get('id'))[1]), None)
        match = match or next(iter(matches), None)
    if not match:
        titles = ', '.join(sorted({e.get('title') or '?' for e in todays})[:8])
        wanted = f" {leg}" if leg else ''
        return {"status": "error",
                "message": f"I couldn't find the{wanted} drive for '{event_name}' that day. "
                           f"On the schedule: {titles}."}

    rec = match.get('recurring_event_id')
    use_series = (scope == 'series' and bool(rec))
    match_id = str(match.get('id') or '')
    parent_id, _matched_leg = _assist.split_leg(match_id)
    selected_id = match_id if leg else parent_id
    key = _assist.scoped_key(selected_id, rec, 'series' if use_series else 'instance')

    if clear or not contact_name:
        # Both keys: "we're driving it after all" must not leave a standing
        # series row behind to re-cover the occurrence on the next solve.
        _assist.clear_coverage(selected_id, rec)
        what = f" {leg.replace('dropoff', 'drop-off')}" if leg else ''
        return {"status": "success", "schedule_dirty": True,
                "message": f"{match.get('title')}{what} is back on the family's plate — "
                           f"I'll work out who drives."}

    contact = _find_assist_contact(contact_name)
    if not contact:
        known = ', '.join(c.get('relation_label') or c.get('name')
                          for c in storage.get_assist_contacts()) or 'nobody yet'
        return {"status": "error",
                "message": f"I don't know '{contact_name}'. Outside hands I know: {known}. "
                           f"A parent can add them in Drives → ⚙ Settings → Outside hands."}
    storage.set_assist_assignment(
        key, contact['id'], scope=('series' if use_series else 'instance'),
        event_date=('' if use_series else str(match.get('start') or '')[:10]),
        event_title=match.get('title') or '')
    who = contact.get('relation_label') or contact.get('name')
    what = f" {leg.replace('dropoff', 'drop-off')}" if leg else ''
    span = (" every time it comes round" if use_series
            else f" on {day.strftime('%A %d %b')}")
    return {"status": "success", "schedule_dirty": True,
            "message": f"{who} is covering {match.get('title')}{what}{span} — "
                       f"I've taken it off the family's plate."}


def get_assist_coverage(target_date: str = None) -> Dict[str, Any]:
    """What outside help is covering on a day, and who to ring."""
    import datetime
    from services import storage
    day = _parse_fuzzy_date(target_date or 'today')
    sched = storage.get_cached_schedule() or {}
    # From STORAGE, not the cache. Coverage is written the moment somebody
    # says "Emma's mom is taking them"; the schedule cache only learns about
    # it when the background re-solve lands. Reading the cache here would
    # answer "nobody is covering anything" to a question asked ten seconds
    # after the change — the events come from the cache, the truth does not.
    assist_map = storage.get_assist_assignment_map()
    if not assist_map:
        return {"status": "success",
                "message": f"Nobody outside the family is covering anything on "
                           f"{day.strftime('%A %d %b')}."}
    by_id = {c['id']: c for c in storage.get_assist_contacts(include_inactive=True)}
    lines = []
    from services import assist as _assist
    for ev in sched.get('events', []):
        # Resolved instance-then-series, or a standing arrangement would read
        # as "nobody is covering anything" here while the solver honours it.
        covering = _assist.coverage_for(assist_map, ev)
        if not covering:
            continue
        try:
            start = datetime.datetime.fromisoformat(str(ev.get('start')))
            if start.date() != day:
                continue
            stamp = start.strftime('%I:%M %p').lstrip('0')
        except (ValueError, TypeError):
            stamp = ''
        c = by_id.get(covering) or {}
        who = c.get('relation_label') or c.get('name') or 'someone'
        phone = f" ({c['phone']})" if c.get('phone') else ''
        lines.append(f"{stamp} {ev.get('title') or 'Event'} — {who}{phone}".strip())
    if not lines:
        return {"status": "success",
                "message": f"Nobody outside the family is covering anything on "
                           f"{day.strftime('%A %d %b')}."}
    return {"status": "success",
            "message": "Covered by outside hands:\n" + "\n".join(lines)}


def announce_to_room(room: str, message: str, recipient_name: str = None,
                     sender_driver_id: str = None, from_member: str = None) -> Dict[str, Any]:
    """Speak in a room over HA (services/announce.py owns the how). Unlike the
    message tools the SENDER is optional — an announcement is the house
    talking, and refusing to call dinner because the wall panel doesn't know
    who tapped it would be the wrong trade. When a sender is resolvable the
    DM echo is attributed to them; otherwise Argyle signs it."""
    from services import announce as announce_svc
    sender, _ = _resolve_actor(sender_driver_id, from_member)
    recipient = _find_member_fuzzy(recipient_name) if recipient_name else None
    return announce_svc.announce_and_echo(room, message,
                                          sender=sender, recipient=recipient)


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
    # Same for people who have since been archived — they still wrote what they wrote.
    names = {m['id']: m.get('name', '?')
             for m in storage.get_all_members(include_system=True,
                                              include_archived=True)}
    lines = []
    for m in msgs:
        t = datetime.datetime.fromtimestamp(m.get('ts', 0)).strftime('%a %I:%M %p').lstrip('0')
        lines.append(f"{names.get(m.get('sender_member_id'), 'Unknown')} ({t}): {m.get('body', '')}")
    return {"status": "success", "message": "Recent family messages:\n" + "\n".join(lines)}


def list_chores() -> Dict[str, Any]:
    from services import storage
    chores = storage.get_offered_chores()   # out of season: not on the list
    names = {m['id']: m.get('name', '?') for m in storage.get_all_members(include_archived=True)}
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


def list_open_findings() -> Dict[str, Any]:
    """"What needs me?" — answered from the records, not from a re-scan.

    The whole point of the findings table is that the answer is a stored fact
    rather than something recomputed per asker, so the app, the push and the
    agent can never disagree about what is still outstanding.
    """
    from services import findings as _f
    rows = _f.open_findings()
    if not rows:
        return {"status": "success", "message": "Nothing needs you right now."}
    decide = [r for r in rows if r.get('severity') == 'decide']
    approve = [r for r in rows if r.get('severity') == 'approve']
    parts = []
    if decide:
        parts.append("Needs a decision: " + "; ".join(r['line'] for r in decide[:4]))
    if approve:
        parts.append("One tap each: " + "; ".join(r['line'] for r in approve[:4]))
    rest = len(rows) - len(decide[:4]) - len(approve[:4])
    if rest > 0:
        parts.append(f"...and {rest} more on the list")
    return {"status": "success", "message": " | ".join(parts)}


def research_question(question: str) -> Dict[str, Any]:
    """Look something up on the web and answer with sources attached.

    For the practical questions a household actually has — what a service
    costs around here, whether a provider is licensed, which beginner course
    people recommend. Every fact comes back with the page it was read from,
    and a fact the model could not source is dropped before it gets here."""
    from services import web as _web
    res = _web.research(question)
    status = res.get('status')
    if status == 'ok':
        return {"status": "success", "answer": res.get('answer') or '',
                "facts": res.get('facts') or [],
                "sources": res.get('sources') or []}
    friendly = {
        'disabled': "Web research is switched off in settings.",
        'no_key': "There's no search key configured for research.",
        'capped': res.get('message') or "That's this month's research budget.",
        'reserved': res.get('message') or "The shared search allowance is reserved.",
        'no_results': "I couldn't find anything readable on that.",
    }
    return {"status": "error",
            "message": friendly.get(status, res.get('message') or "Search failed.")}


def list_insights(member_role: str = None) -> Dict[str, Any]:
    """Things Argyle's Mind is currently keeping an eye on ('the Argyle
    noticed lane'). member_role is filled by the DISPATCH LAYER from the
    resolved caller identity (acting_member / driver's member), never taken
    from the model — mind.visible_insights() is the same server-side
    sensitivity gate the /api/mind/insights endpoint uses, and a caller with
    no resolved identity gets the same no-sensitive-rows payload as the wall
    panel."""
    from services import mind as _mind
    viewer = {'role': member_role} if member_role else None
    rows = _mind.visible_insights(viewer)
    return {"insights": [{"id": r['id'], "line": r['line'],
                          "detail": r.get('detail') or '',
                          "category": r.get('category')} for r in rows]}


def dismiss_insight(insight_id: str, member_role: str = None) -> Dict[str, Any]:
    """Dismiss one of the Mind's insights (the family said no). Dismissing
    records family feedback the graduation logic learns from, so — mirroring
    the /api/mind/insights/{id}/dismiss endpoint's parent/adult gate — a
    caller resolved (by the dispatch layer, never the model) to child/helper/
    guest is refused; an unresolved caller (legacy admin/voice contexts with
    no identity) is trusted, same as the rest of the open-admin toolset."""
    if member_role in ('child', 'helper', 'guest'):
        return {"status": "error",
                "message": "Only a parent or adult can dismiss this."}
    import time as _t
    from services import storage as _s
    ok = _s.update_mind_insight(insight_id, {'state': 'retired',
                                             'outcome': 'dismissed',
                                             'resolved_ts': _t.time()})
    return {"status": "success" if ok else "error"}


# --- Situations: the card's verbs as tools (spec §4). acting_member is
# resolved by the DISPATCH LAYER, never taken from the model. ---------------

def _situation_lines(rows: list) -> str:
    out = []
    for s in rows:
        nxt = (s.get('next_step') or {}).get('label') or '-'
        asks = '; '.join(f"asked {a.get('to_name')} by {a.get('channel')}: {a.get('state')}"
                         + (f"/{a['outcome']}" if a.get('outcome') else '')
                         for a in (s.get('asks') or []) if a.get('state') != 'withdrawn')
        out.append(f"- [{s['kind']}] {s['title']}: {s.get('status_note') or ''} -> next: {nxt}"
                   + (f" ({asks})" if asks else ''))
    return '\n'.join(out)


NO_FOCUS = "Which one? Ask me what needs your attention first, or name it."


NOT_ALOUD = "That one is not for a shared speaker; open it on your phone."


def _sensitive(kind: str, row: dict) -> bool:
    return kind == 'insight' and (row or {}).get('sensitivity') == 'sensitive'


def _resolve_situation(ref: str, kind: str = None, viewer: dict = None, focus_key: str = None,
                       spoken: bool = False):
    """An id, a title fragment, or - with no ref - the conversation's focus.
    Naming one makes it the focus. Never guesses between candidates. `spoken`
    is a room: a sensitive insight is never matched, listed or made the focus
    there, by id or by fragment."""
    from services import situations as _sit, triage as _tri
    ref = (ref or '').strip()
    if not ref:
        f = _tri.get_focus(focus_key)
        if not f:
            return None, NO_FOCUS
        row = _sit.load(f['kind'], f['id'])
        if not row or not _sit.can_see(f['kind'], row, viewer):
            return None, NO_FOCUS
        if spoken and _sensitive(f['kind'], row):
            return None, NOT_ALOUD
        return (f['kind'], f['id']), None
    found = None
    for k in ([kind] if kind in _sit.KINDS else _sit.KINDS):
        row = _sit.load(k, ref)
        if row:
            if not _sit.can_see(k, row, viewer):
                return None, "That one is not yours to see."
            if spoken and _sensitive(k, row):
                return None, NOT_ALOUD
            found = (k, ref)
            break
    if not found:
        rows = _sit.list_situations(viewer, kinds=(kind,) if kind in _sit.KINDS else None, spoken=spoken)
        hits = [s for s in rows if ref.lower() in (s.get('title') or '').lower()]
        if len(hits) == 1:
            found = (hits[0]['kind'], hits[0]['id'])
        elif not hits:
            return None, f"Nothing open matches '{ref}'."
        else:
            names = '; '.join(h['title'] for h in hits[:5])
            return None, f"Which one: {names}?"
    row = _sit.load(found[0], found[1]) or {}
    title = {'finding': row.get('line'), 'insight': row.get('line'),
             'thread': row.get('title'), 'mission': row.get('goal')}.get(found[0]) or ''
    _tri.set_focus(focus_key, found[0], found[1], title)
    return found, None


def list_situations(kinds: str = None, limit: int = 10, acting_member: dict = None,
                    spoken: bool = False) -> Dict[str, Any]:
    from services import situations as _sit
    want = tuple(k for k in (kinds or '').split(',') if k in _sit.KINDS) or None
    rows = _sit.list_situations(acting_member, kinds=want, spoken=spoken)[:max(1, min(int(limit or 10), 30))]
    if not rows:
        return {"status": "success", "message": "Nothing needs anyone right now.", "situations": []}
    return {"status": "success", "message": _situation_lines(rows), "situations": rows}


def next_situation(skip_current: bool = False, acting_member: dict = None, focus_key: str = None) -> Dict[str, Any]:
    """The one most pressing situation as a sentence; sets the conversation's
    focus. Terminal: the message IS the spoken answer. Sensitive insights are
    never spoken (triage.next_for lists with spoken=True)."""
    from services import triage as _tri
    # The raw entry, not get_focus: a focus whose situation was handled
    # between turns is dead, and get_focus would drop it with the cursor
    # "next" needs to continue from.
    had = _tri.has_entry(focus_key)
    s = _tri.next_for(acting_member, focus_key, skip_current=bool(skip_current))
    if s is None:
        msg = ("That's everything. Nothing else needs anyone right now." if (skip_current and had)
               else "Nothing needs anyone right now.")
        return {"status": "success", "message": msg, "situation": None, "focus": None}
    line = _tri.spoken(s)
    if not focus_key:
        # No conversation to hold the focus: end with the title so the
        # follow-up can name it.
        line += f" (Say '{s.get('title')}' to take it further.)"
    return {"status": "success", "message": line, "situation": s, "focus": _tri.get_focus(focus_key)}


def explain_situation(ref: str = '', kind: str = None, acting_member: dict = None,
                      focus_key: str = None, spoken: bool = False) -> Dict[str, Any]:
    from services import situations as _sit
    found, why = _resolve_situation(ref, kind, acting_member, focus_key, spoken)
    if not found:
        return {"status": "error", "message": why}
    s = _sit.view(found[0], found[1], acting_member)
    opts = '\n'.join(f"  {i + 1}. {o['label']} [{o['verb']}, option {o['id']}]" for i, o in enumerate(s['options']))
    asks = '\n'.join(f"  - asked {a.get('to_name')} by {a.get('channel')}: {a.get('what')}: {a.get('state')}"
                     + (f" / {a['outcome']}" if a.get('outcome') else '') for a in s['asks']) or '  (none)'
    msg = (f"{s['title']}\nStatus: {s['status_note']}\nOptions:\n{opts}\nAsks so far:\n{asks}")
    return {"status": "success", "message": msg, "situation": s}


def act_on_situation(ref: str = '', verb: str = '', option_id: str = None, kind: str = None, text: str = None,
                     next_action_at: str = None, acting_member: dict = None, focus_key: str = None,
                     spoken: bool = False) -> Dict[str, Any]:
    from services import situations as _sit
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a parent or adult can do that."}
    found, why = _resolve_situation(ref, kind, acting_member, focus_key, spoken)
    if not found:
        return {"status": "error", "message": why}
    k, sid = found
    if not option_id:
        all_opts = _sit.options_for(k, _sit.load(k, sid))
        opts = [o for o in all_opts if o['verb'] == verb]
        # "Handle it": the highlighted next step wins when it carries this verb.
        if len(opts) > 1 and all_opts and all_opts[0]['verb'] == verb:
            opts = [all_opts[0]]
        if len(opts) != 1:
            return {"status": "error",
                    "message": ("Say which option: " + '; '.join(f"{o['label']} ({o['id']})" for o in opts))
                    if opts else f"'{verb}' is not on the table for that one."}
        option_id = opts[0]['id']
    # Only what the person SAID goes in; an option built from a reading
    # arrives pre-filled, and an empty text must not blank it.
    payload = {}
    if verb in ('answer', 'draft', 'research') and (text or '').strip():
        payload['text'] = text.strip()
    if verb == 'advance':
        if (text or '').strip():
            payload['next_action'] = text.strip()
        if next_action_at:
            payload['next_action_at'] = next_action_at
    res = _sit.act(k, sid, verb, option_id=option_id, payload=payload, actor=acting_member)
    if res.get('status') == 'refused':
        return {"status": "error", "message": res.get('message')}
    return res


def start_ask(ref: str = '', to_name: str = '', what: str = '', channel: str = '', kind: str = None,
              acting_member: dict = None, focus_key: str = None, spoken: bool = False) -> Dict[str, Any]:
    from services import situations as _sit, asks as _asks
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a parent or adult can ask."}
    found, why = _resolve_situation(ref, kind, acting_member, focus_key, spoken)
    if not found:
        return {"status": "error", "message": why}
    k, sid = found
    row = _sit.load(k, sid)
    to = {'name': to_name}
    from services import storage
    member = next((m for m in storage.get_all_members() if (m.get('name') or '').lower() == (to_name or '').lower()), None)
    contact = next((c for c in storage.get_assist_contacts() if (c.get('name') or '').lower() == (to_name or '').lower()), None)
    if member:
        to['member_id'] = member['id']
    elif contact:
        to['contact_id'] = contact['id']
    # The commitment is the SERVER's when an option binds it. A `what` the
    # model wrote that differs from the option's is a different ask: recorded
    # as written, unbound, so a yes never applies something they did not agree to.
    unlocks, bound_what = None, None
    for o in _sit.options_for(k, row):
        if o['verb'] != 'ask':
            continue
        if to.get('contact_id') and (o['payload'].get('to') or {}).get('contact_id') == to['contact_id']:
            unlocks, bound_what = o['payload'].get('unlocks'), o['payload'].get('what')
            break
        if o['id'] == 'ask:new' and unlocks is None:
            unlocks, bound_what = o['payload'].get('unlocks'), o['payload'].get('what')
    what = (what or '').strip()
    if bound_what and not what:
        what = bound_what
    elif bound_what and what != bound_what:
        unlocks = None
    if unlocks and unlocks.get('action_type') == 'assist_assignment' and to.get('contact_id'):
        unlocks = {**unlocks, 'payload': {**unlocks['payload'], 'contact_id': to['contact_id']}}
    event = _sit._cached_event(((unlocks or {}).get('payload') or {}).get('event_id')) if unlocks else None
    res = _asks.create(k, sid, to, what, channel, acting_member['id'], unlocks=unlocks, event=event)
    if res.get('status') != 'success':
        return {"status": "error", "message": res.get('message')}
    a = res['ask']
    how = {'chauffeur': f"Sent to {a['to_name']} on Chauffeur with Yes/No.",
           'email': "Here's the email. Copy it into your mail app, then tell me when it's sent:",
           'text': "Here's the text. Copy it, send it, then tell me when it's sent:",
           'in_person': "Here's what to say. Tell me once you've asked:"}[channel]
    draft = (f"Subject: {a['draft_subject']}\n\n" if a.get('draft_subject') else '') + (a.get('draft_body') or '')
    return {"status": "success", "ask_id": a['id'], "draft": draft,
            "message": f"{how}\n\n{draft}" if channel != 'chauffeur' else how}


def _focus_ask(focus_key: str, acting_member: dict):
    """The focus situation's ONE live ask, or a refusal naming the choice."""
    from services import triage as _tri
    if not _tri.get_focus(focus_key):
        return None, NO_FOCUS
    live = _tri.focus_live_asks(focus_key, acting_member)
    if len(live) == 1:
        return live[0]['id'], None
    if not live:
        return None, "Nobody has been asked about that one yet."
    names = ', or '.join(f"{a.get('to_name')} by {a.get('channel')}" for a in live)
    return None, f"Which ask: {names}?"


def mark_ask_sent(ask_id: str = None, acting_member: dict = None, focus_key: str = None) -> Dict[str, Any]:
    from services import asks as _asks
    if not ask_id:
        ask_id, why = _focus_ask(focus_key, acting_member)
        if not ask_id:
            return {"status": "error", "message": why}
    res = _asks.mark_sent(ask_id, acting_member)
    return {**res, "status": "error" if res.get('status') == 'refused' else res.get('status')}


def answer_ask(ask_id: str = None, answer: str = None, acting_member: dict = None,
               focus_key: str = None) -> Dict[str, Any]:
    from services import asks as _asks, storage
    if not ask_id:
        ask_id, why = _focus_ask(focus_key, acting_member)
        if not ask_id:
            return {"status": "error", "message": why}
    recipient = (storage.get_ask(ask_id) or {}).get('to_member_id')
    res = _asks.answer(ask_id, (answer or '').lower(), acting_member,
                       reported=(acting_member or {}).get('id') != recipient)
    return {**res, "status": "error" if res.get('status') == 'refused' else res.get('status')}


# --- The family's mailbox (browse missions §3): read-only, parents and adults. --

def _mail_reader(acting_member: dict):
    """ALLOWLIST: a resolved parent or adult. An anonymous panel (actor None)
    and a child, helper or guest are refused the same way."""
    if not (acting_member or {}).get('id') or (acting_member or {}).get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a signed-in parent or adult can search the family mailbox."}
    return None


def search_mail(query: str, since_days: int = 365, limit: int = 5, acting_member: dict = None,
                spoken: bool = False) -> Dict[str, Any]:
    """`spoken`: the router sets it when a caller with no identity (HA voice,
    the admin widget) acts as the parent of record — a ROOM, where anybody
    may be listening. A room hears who wrote and about what, never the body."""
    refusal = _mail_reader(acting_member)
    if refusal:
        return refusal
    from services import mail_search as _ms
    res = _ms.search(query or '', since_days=since_days or 365, limit=limit or 5)
    if res.get('status') != 'success':
        return {"status": "error", "message": res.get('message') or 'mailbox error'}
    hits = res['hits']
    if not hits:
        return {"status": "success", "message": f"Nothing in the family mailbox matches '{query}'.", "hits": []}
    if spoken:
        hits = [{k: v for k, v in h.items() if k != 'snippet'} for h in hits]
        lines = [f"- uid {h['uid']} · {h['date'][:10]} · {h['from']} · {h['subject']}" for h in hits]
        return {"status": "success", "message": "Found in the family mailbox (headers only out loud):\n" + '\n'.join(lines),
                "hits": hits}
    lines = [f"- uid {h['uid']} · {h['date'][:10]} · {h['from']} · {h['subject']}: {h['snippet'][:160]}" for h in hits]
    return {"status": "success", "message": "Found in the family mailbox:\n" + '\n'.join(lines), "hits": hits}


def read_mail(uid: int, acting_member: dict = None, spoken: bool = False) -> Dict[str, Any]:
    refusal = _mail_reader(acting_member)
    if refusal:
        return refusal
    if spoken:
        return {"status": "error", "message": "I can't read the family's mail out loud — open it on your phone."}
    from services import mail_search as _ms
    res = _ms.read(uid)
    if res.get('status') != 'success':
        return {"status": "error", "message": res.get('message') or 'mailbox error'}
    return {"status": "success", "message": f"{res['subject']} — from {res['from']} {res['date'][:10]}\n\n{res['text']}", **res}


def start_mission_for(goal: str, title: str = None, acting_member: dict = None, focus_key: str = None) -> Dict[str, Any]:
    """'Get the dishwasher fixed': open a thread and a mission on it, and
    make the thread the thing we are talking about. Parents and adults
    (voice as the parent of record). One of each: a live mission on an open
    thread about the same thing is named, not doubled."""
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a parent or adult can start that."}
    from services import storage, threads as _threads, missions as _missions, triage as _tri
    goal = (goal or '').strip()
    if not goal:
        return {"status": "error", "message": "Say what to get done."}
    settings = storage.get_settings() or {}
    if not settings.get('missions_enabled', False):
        return {"status": "error", "message": "Missions are off (Missions settings)."}
    # What launch would refuse, asked BEFORE the thread exists: a refusal must
    # not leave an orphan thread behind.
    from services import model_pools as _mp
    if not _mp.api_key_for_pool('pro', settings):
        return {"status": "error", "message": "Missions need the paid Gemini key (Missions settings)."}
    import datetime as _dt
    cap = int(settings.get('mission_cap_launch', _missions.CAPS_DEFAULT['launch']))
    used = int((storage.get_app_state(f"mission_calls:{_dt.date.today().isoformat()}") or {}).get('launch', 0))
    if used >= cap:
        return {"status": "error", "message": f"That's {cap} missions today — the cap resets tomorrow."}
    words = [w for w in goal.lower().split() if len(w) > 2][:3]
    for m in storage.get_missions(status=['running', 'browsing', 'waiting_user', 'waiting_retry']):
        if m.get('origin_kind') != 'thread':
            continue
        t = storage.get_thread(m.get('origin_ref') or '')
        hay = ((t or {}).get('title', '') + ' ' + (t or {}).get('goal', '') + ' ' + m.get('goal', '')).lower()
        if t and t.get('state') not in ('done', 'dropped') and words and all(w in hay for w in words):
            _tri.set_focus(focus_key, 'thread', t['id'], t.get('title') or '')
            return {"status": "success", "thread_id": t['id'], "mission_id": m['id'],
                    "message": f"That's already under way: \"{t.get('title')}\". I'll come back when I have something or need you."}
    tid = _threads.create(title=(title or goal)[:80], owner_member_id=acting_member['id'], goal=goal, kind='vendor',
                          created_by=acting_member['id'])
    res = _missions.launch(goal, origin_kind='thread', origin_ref=tid, created_by=acting_member['id'], tier='mission')
    if res.get('status') not in ('success', 'launched') or not res.get('mission_id'):
        return {"status": "error", "message": res.get('message') or 'could not start the mission', "thread_id": tid}
    _tri.set_focus(focus_key, 'thread', tid, (title or goal)[:80])
    return {"status": "success", "thread_id": tid, "mission_id": res['mission_id'],
            "message": "On it. I'll come back when I have something or need you."}


def _match_thread(thread_title: str):
    """Fuzzy title match against open threads, same shape as `_match_task` —
    the model knows a thread by what it's about, never by its id."""
    from services import storage
    q = (thread_title or '').strip().lower()
    rows = storage.get_threads(include_closed=False)
    if not q:
        return None, rows
    exact = [t for t in rows if (t.get('title') or '').lower() == q]
    if len(exact) == 1:
        return exact[0], rows
    part = [t for t in rows if q in (t.get('title') or '').lower()]
    if len(part) == 1:
        return part[0], rows
    return None, rows


def _thread_reader(acting_member: dict):
    """ALLOWLIST, not a blocklist: a thread names a counterparty and what
    the family is chasing with them, and /threads is deliberately hidden
    from kiosks so that data stays off shared screens. /api/chat is
    WALL_OR_SERVICE, so an anonymous kitchen wall panel reaches these tools
    with NO resolved actor — a `role not in (...)` blocklist waves that
    None straight through. Reads require a RESOLVED member of any role;
    writes (`_thread_writer`) require a resolved parent/adult, the same
    discipline as main.py's `_mind_actor`."""
    if not (acting_member or {}).get('id'):
        return {"status": "error",
                "message": "Threads are for signed-in family members — "
                           "I can't show them here."}
    return None


def _thread_writer(acting_member: dict, verb: str):
    """Parent/adult, resolved — see `_thread_reader` for why this is an
    allowlist. An unresolved actor (wall panel, anonymous chat) and a
    resolved child/helper/guest are refused the same way."""
    if not (acting_member or {}).get('id') \
            or (acting_member or {}).get('role') not in ('parent', 'adult'):
        return {"status": "error",
                "message": f"Only a signed-in parent or adult can {verb}."}
    return None


def list_threads(state: str = None, owner_name: str = None,
                 include_closed: bool = False,
                 acting_member: dict = None) -> Dict[str, Any]:
    """Open loops with somebody outside the family — the pest control
    company, the school waitlist. A read for any RESOLVED member (an
    anonymous wall panel is refused — see `_thread_reader`), same rows as
    GET /api/threads; each is annotated with the same stall reason
    (`services.threads.is_stalled`) that page and the nightly sweep use."""
    refusal = _thread_reader(acting_member)
    if refusal:
        return refusal
    from services import threads as _threads
    from services import storage as _storage
    owner_id = None
    if owner_name:
        m = _find_member_fuzzy(owner_name)
        if not m:
            return {"status": "error",
                    "message": f"I couldn't find '{owner_name}'. Family members: {_member_names()}."}
        owner_id = m['id']
    rows = _storage.get_threads(state=state, owner=owner_id, include_closed=include_closed)
    if not rows:
        return {"status": "success", "message": "No open threads right now."}
    names = {m['id']: m.get('name') for m in _storage.get_all_members(include_archived=True)}
    lines = []
    for t in rows[:15]:
        bits = [t.get('title') or 'Thread']
        holder = names.get(t.get('owner_member_id') or '')
        if holder:
            bits.append(holder)
        if t.get('next_action'):
            na = t['next_action']
            if t.get('next_action_at'):
                na += f" by {t['next_action_at']}"
            bits.append(na)
        reason = _threads.is_stalled(t)
        if reason:
            bits.append(reason.upper())
        lines.append(" — ".join(bits))
    return {"status": "success", "message": "Open threads:\n" + "\n".join(lines)}


def create_thread(title: str, goal: str = None, kind: str = None,
                  counterparty_name: str = None, counterparty_email: str = None,
                  next_action: str = None, next_action_at: str = None,
                  acting_member: dict = None) -> Dict[str, Any]:
    """Open a new thread — a promise somebody outside the family made that
    hasn't closed yet. Parent/adult work, same discipline as dismiss_insight:
    `acting_member` is resolved by the dispatch layer at agent_router.py,
    never taken from the model, and — when it resolves — becomes the
    thread's owner and its `created_by`, same as POST /api/threads does with
    the signed-in caller."""
    refusal = _thread_writer(acting_member, 'open a thread')
    if refusal:
        return refusal
    title = (title or '').strip()
    if not title:
        return {"status": "error", "message": "What is the thread about?"}
    from services import threads as _threads
    thread_id = _threads.create(
        title=title,
        owner_member_id=(acting_member or {}).get('id'),
        goal=(goal or '').strip(),
        kind=(kind or 'project').strip().lower() or 'project',
        counterparty_name=(counterparty_name or '').strip(),
        counterparty_email=(counterparty_email or '').strip(),
        next_action=(next_action or '').strip(),
        next_action_at=next_action_at,
        created_by=(acting_member or {}).get('id'))
    return {"status": "success", "id": thread_id,
            "message": f"Opened a thread: {title}."}


def update_thread_action(thread_title: str, next_action: str,
                         next_action_at: str = None, note: str = None,
                         acting_member: dict = None) -> Dict[str, Any]:
    """Set the next thing that has to happen on a thread, and when
    (wraps `services.threads.advance`). Parent/adult work, same gate as
    `create_thread`; `acting_member` comes from the dispatch layer."""
    refusal = _thread_writer(acting_member, 'update a thread')
    if refusal:
        return refusal
    thread, rows = _match_thread(thread_title)
    if not thread:
        open_titles = ', '.join(t.get('title') or '?' for t in rows[:8]) or 'nothing open'
        return {"status": "error",
                "message": f"I couldn't pin down '{thread_title}'. Open threads: {open_titles}."}
    from services import threads as _threads
    ok = _threads.advance(thread['id'], (next_action or '').strip(),
                         next_action_at=next_action_at, note=note,
                         who=(acting_member or {}).get('id'))
    if not ok:
        return {"status": "error", "message": "That thread is gone."}
    msg = f"Next on \"{thread['title']}\": {next_action}" if next_action \
        else f"Updated \"{thread['title']}\"."
    if next_action_at:
        msg += f" by {next_action_at}"
    return {"status": "success", "message": msg}


def add_thread_note(thread_title: str, text: str, url: str = None,
                    acting_member: dict = None) -> Dict[str, Any]:
    """Log movement on a thread that isn't a change of plan — a call made, a
    voicemail left (wraps `services.threads.note`). Parent/adult work, same
    gate as `create_thread`; `acting_member` comes from the dispatch layer."""
    refusal = _thread_writer(acting_member, 'add a note')
    if refusal:
        return refusal
    text = (text or '').strip()
    if not text:
        return {"status": "error", "message": "What happened?"}
    thread, rows = _match_thread(thread_title)
    if not thread:
        open_titles = ', '.join(t.get('title') or '?' for t in rows[:8]) or 'nothing open'
        return {"status": "error",
                "message": f"I couldn't pin down '{thread_title}'. Open threads: {open_titles}."}
    from services import threads as _threads
    ok = _threads.note(thread['id'], text, who=(acting_member or {}).get('id'), url=url)
    if not ok:
        return {"status": "error", "message": "That thread is gone."}
    return {"status": "success", "message": f"Noted on \"{thread['title']}\": {text}"}


def draft_thread_message(thread_title: str, intent: str = None,
                         acting_member: dict = None) -> Dict[str, Any]:
    """Ask Argyle to propose a subject/body for a thread and STOP THERE
    (wraps `services.threads.draft_message`, which never imports
    `services.mailer` — it cannot send even by accident, and neither can
    this wrapper: there is no send tool in this catalog at all). The draft
    is returned as words for a person to carry to the Threads page, edit,
    and send with their own tap — the "never sends unread" boundary lives
    in that separation. Parent/adult work, same gate as the other writes."""
    refusal = _thread_writer(acting_member, 'draft a message')
    if refusal:
        return refusal
    thread, rows = _match_thread(thread_title)
    if not thread:
        open_titles = ', '.join(t.get('title') or '?' for t in rows[:8]) or 'nothing open'
        return {"status": "error",
                "message": f"I couldn't pin down '{thread_title}'. Open threads: {open_titles}."}
    from services import threads as _threads
    res = _threads.draft_message(thread['id'], intent=(intent or '').strip())
    if res.get('status') != 'ok':
        reason = res.get('reason') or "the model didn't come back with a draft"
        return {"status": "error",
                "message": f"Couldn't draft that just now — {reason}."}
    to = res.get('to') or ''
    to_line = f"\nTo: {to}" if to else ''
    return {"status": "success", "subject": res['subject'], "body": res['body'],
            "to": to,
            "message": (f"Here's a draft for \"{thread['title']}\" — nothing has "
                        f"been sent, and I can't send it: a person reviews and "
                        f"sends it from the Threads page.{to_line}\n"
                        f"Subject: {res['subject']}\n\n{res['body']}")}


def launch_mission(goal: str, thread_title: str = None, actor: dict = None) -> dict:
    """Allowlist: a resolved parent/adult launches; anyone else is refused —
    /api/chat is WALL_OR_SERVICE, so an anonymous panel arrives with no actor
    and must not walk through a role blocklist."""
    if not actor or (actor.get('role') or '') not in ('parent', 'adult'):
        return {'status': 'refused',
                'message': 'Only a parent or adult can start a mission.'}
    if not (thread_title or '').strip():
        # A new goal with no thread named is start_mission_for's job: the
        # thread, the focus and the "On it." come with it (browse missions §4).
        return start_mission_for(goal, acting_member=actor)
    return handle_launch_mission({'goal': goal, 'thread_title': thread_title,
                                  '_member_id': actor.get('id')})


def close_thread(thread_title: str, state: str = None,
                 acting_member: dict = None) -> Dict[str, Any]:
    """End a thread — `done` when it resolved, `dropped` when it didn't and
    won't (wraps `services.threads.close`). The state must be said, and only
    those two are accepted — anything else is refused, the same enum
    POST /api/threads/{id}/close holds. Parent/adult work, same gate as
    `create_thread`; `acting_member` comes from the dispatch layer."""
    refusal = _thread_writer(acting_member, 'close a thread')
    if refusal:
        return refusal
    state = (state or '').strip().lower()
    if state not in ('done', 'dropped'):
        return {"status": "error",
                "message": "A thread can only close as done or dropped — "
                           "which is it?"}
    thread, rows = _match_thread(thread_title)
    if not thread:
        open_titles = ', '.join(t.get('title') or '?' for t in rows[:8]) or 'nothing open'
        return {"status": "error",
                "message": f"I couldn't pin down '{thread_title}'. Open threads: {open_titles}."}
    from services import threads as _threads
    ok = _threads.close(thread['id'], state=state,
                        who=(acting_member or {}).get('id'))
    if not ok:
        return {"status": "error", "message": "That thread is gone."}
    return {"status": "success",
            "message": f"Closed \"{thread['title']}\" as {state}."}


def _program_reader(acting_member: dict):
    """ALLOWLIST, not a blocklist: a program is somebody's personal ambition
    — reserved practice time, a session log, a curated plan — and /api/chat
    is WALL_OR_SERVICE, so an anonymous kitchen wall panel reaches these
    tools with NO resolved actor. A `role not in (...)` blocklist waves that
    None straight through, same trap `_thread_reader` closes. Reads require
    a RESOLVED member of any role."""
    if not (acting_member or {}).get('id'):
        return {"status": "error",
                "message": "Programs are for signed-in family members — "
                           "I can't show them here."}
    return None


def _program_writer(acting_member: dict, verb: str):
    """A resolved member, full stop — see `_program_reader` for why this is
    an allowlist. Which member may act on WHICH program (your own freely, a
    parent/adult stands in otherwise, matching `main.py`'s
    `_program_permission_or_refuse`) needs the program row in hand, so that
    half is checked per-call by `_program_owns_or_parent` below; this only
    closes the unresolved-caller gap."""
    if not (acting_member or {}).get('id'):
        return {"status": "error",
                "message": f"Only a signed-in family member can {verb}."}
    return None


def _program_owns_or_parent(acting_member: dict, row: dict, verb: str):
    """The arc's ownership rule, applied to one program: free rein on your
    own, a parent/adult stands in for anybody else's — the chat mirror of
    `main.py`'s `_program_permission_or_refuse`."""
    if row.get('member_id') == acting_member.get('id'):
        return None
    if (acting_member.get('role') or '') in ('parent', 'adult'):
        return None
    return {"status": "error",
            "message": f"Only a parent or adult can {verb} for someone else."}


def _program_scope_id(acting_member: dict):
    """None (the household) for a parent/adult, otherwise the caller's own
    id — the same partition `list_programs` shows. Pulled out so
    `_match_program` can scope BEFORE it matches: a program is somebody's
    personal ambition, not household-visible the way a thread is, and that
    has to hold for the not-found hint too, not just the happy path."""
    if (acting_member.get('role') or '') in ('child', 'helper', 'guest'):
        return acting_member.get('id')
    return None


def _resolve_named_member_or_refuse(acting_member: dict, name: str, verb_phrase: str):
    """Fuzzy-resolve `name` to a member, refusing unless it's the caller's
    own identity or the caller is a parent/adult. Returns `(member, None)`
    or `(None, refusal_dict)` — shared by `list_programs` and
    `propose_program`, which both hit exactly this rule."""
    m = _find_member_fuzzy(name)
    if not m:
        return None, {"status": "error",
                      "message": f"I couldn't find '{name}'. Family members: {_member_names()}."}
    if m['id'] != acting_member.get('id') \
            and (acting_member.get('role') or '') not in ('parent', 'adult'):
        return None, {"status": "error",
                      "message": f"Only a parent or adult can {verb_phrase}."}
    return m, None


def _match_program(title: str, acting_member: dict):
    """Fuzzy title match against the programs THIS CALLER may see, same
    shape as `_match_thread` — the model knows a program by what it's
    about, never by its id.

    Scoped with `_program_scope_id` BEFORE the match runs, so the returned
    `rows` — which both callers turn straight into the not-found hint — can
    never contain a program outside what `list_programs` would already show
    this caller. Scoping only the happy path and leaving the failure
    message built from every household program was the actual bug: a
    child's typo would get a sibling's program title read back to them,
    exactly the household-visibility this arc's reads are scoped to avoid.
    """
    from services import storage as _storage
    q = (title or '').strip().lower()
    rows = _storage.get_programs(member_id=_program_scope_id(acting_member),
                                 include_finished=False)
    if not q:
        return None, rows
    exact = [p for p in rows if (p.get('title') or '').lower() == q]
    if len(exact) == 1:
        return exact[0], rows
    part = [p for p in rows if q in (p.get('title') or '').lower()]
    if len(part) == 1:
        return part[0], rows
    return None, rows


def list_programs(member_name: str = None, acting_member: dict = None) -> Dict[str, Any]:
    """What has a real plan attached right now — the wall card's list, in
    words ('what programs are going?', 'what is Ben working on?'). A read
    for any RESOLVED member (see `_program_reader`); a child/helper/guest
    sees only their own program unless a parent/adult is asking or naming
    them, the same scope `GET /api/programs` enforces
    (`main.py`'s `_program_list_scope`) — a program is somebody's personal
    ambition, not household-visible the way a thread is."""
    refusal = _program_reader(acting_member)
    if refusal:
        return refusal
    from services import storage as _storage, programs as _prog
    if member_name:
        m, refusal = _resolve_named_member_or_refuse(
            acting_member, member_name, "see someone else's programs")
        if refusal:
            return refusal
        scope_id = m['id']
    else:
        scope_id = _program_scope_id(acting_member)
    rows = _storage.get_programs(member_id=scope_id, include_finished=False)
    if not rows:
        return {"status": "success", "message": "No programs going right now."}
    names = {m['id']: m.get('name') for m in _storage.get_all_members(include_archived=True)}
    lines = []
    for p in rows[:15]:
        prog = _prog.progress(p)
        bits = [p.get('title') or 'Program']
        holder = names.get(p.get('member_id') or '')
        if holder:
            bits.append(holder)
        bits.append(p.get('state') or '?')
        if prog.get('phase'):
            bits.append(f"working on {prog['phase'].get('name')}")
        bits.append(f"{prog['sessions']} session(s) logged")
        lines.append(" — ".join(bits))
    return {"status": "success", "message": "Programs:\n" + "\n".join(lines)}


def program_progress(program_title: str, acting_member: dict = None) -> Dict[str, Any]:
    """How one program is going — sessions logged, minutes, the phase ahead
    (wraps `services.programs.progress`, which is deliberately monotonic: no
    streak, no miss count, no percentage). A read for any RESOLVED member
    (see `_program_reader`), but only on your own program or one you parent
    (`_program_owns_or_parent`) — a program is somebody's personal ambition."""
    refusal = _program_reader(acting_member)
    if refusal:
        return refusal
    from services import programs as _prog
    row, rows = _match_program(program_title, acting_member)
    if not row:
        titles = ', '.join(p.get('title') or '?' for p in rows[:8]) or 'no programs yet'
        return {"status": "error",
                "message": f"I couldn't pin down '{program_title}'. Programs: {titles}."}
    refusal = _program_owns_or_parent(acting_member, row, 'see progress on')
    if refusal:
        return refusal
    p = _prog.progress(row)
    bits = [f"{row.get('title')}: {p['sessions']} session(s)",
            f"{p['minutes']} minutes"]
    if p.get('phase'):
        bits.append(f"working on {p['phase'].get('name')}")
    if p['milestones_hit']:
        bits.append(f"{p['milestones_hit']} milestone(s) hit")
    if row.get('state') == 'paused':
        bits.append('paused')
    return {"status": "success", "message": " — ".join(bits)}


def propose_program(title: str, for_member_name: str = None,
                    sessions_per_week: int = None, minutes: int = None,
                    starting_point: str = None,
                    acting_member: dict = None) -> Dict[str, Any]:
    """Screen the aim, then curate a real plan for it — the chat mirror of
    `POST /api/programs`. The body-goal screen (`programs_curate.screen_aim`)
    runs BEFORE anything else, same as the endpoint and for the same reason:
    a body-composition aim never reaches research and never becomes an
    object somebody could approve later, no matter who is asking — its
    refusal is returned verbatim, so the sentence is the same wherever the
    aim is typed. Proposing for YOURSELF is open to any resolved member (a
    kid proposing their own guitar program is the point); proposing in
    somebody ELSE's name needs a parent/adult, same rule as every other
    program write. Nothing is claimed here — approving is deliberately not a
    chat tool at all; the program sits `proposed` until a person taps
    approve on the Programs page after seeing the footprint."""
    refusal = _program_writer(acting_member, 'start a program')
    if refusal:
        return refusal
    from services import storage as _st, programs_curate as _cur
    # `programs_enabled` governs the whole feature, not only the sweep: with
    # it off, proposing here would still spend a real research run.
    if not _st.get_settings().get('programs_enabled', True):
        return {"status": "error",
                "message": "Programs are switched off for this household."}
    title = (title or '').strip()
    if not title:
        return {"status": "error", "message": "What's the aim?"}
    screen = _cur.screen_aim(title)
    if not screen.get('ok'):
        return {"status": "error", "message": screen.get('message'),
                "alternatives": screen.get('alternatives') or []}
    # Same screen on the starting point, because it is the second free field
    # a person types and a body target typed one box lower is still a body
    # target. Same sentence as the endpoint's, from the same function.
    starting_point = (starting_point or '').strip()
    screen = _cur.screen_starting_point(starting_point)
    if not screen.get('ok'):
        return {"status": "error", "message": screen.get('message'),
                "alternatives": screen.get('alternatives') or []}
    from services import storage as _storage
    member_id = acting_member.get('id')
    member_name = acting_member.get('name') or ''
    member = acting_member
    if for_member_name:
        m, refusal = _resolve_named_member_or_refuse(
            acting_member, for_member_name, 'start a program for someone else')
        if refusal:
            return refusal
        member_id, member_name, member = m['id'], m.get('name') or '', m
    # Clamped, because this schema's bounds are a hint to a model and nothing
    # more: asked for "twice a day" a model says 14, and an unbounded shape
    # hung `propose_slots` forever and wrote a '29:00' window that silently
    # disabled protected time for the whole household.
    from services import programs as _prog
    shape = _prog.clamp_shape({'sessions_per_week': sessions_per_week,
                               'minutes': minutes, 'preferred_days': []})
    curated = _cur.curate(title, shape, member_name=member_name,
                          member=member, starting_point=starting_point)
    pid = _storage.add_program({
        'member_id': member_id, 'title': title, 'shape': shape,
        'starting_point': starting_point,
        'phases': curated['phases'], 'source': curated['source'],
        'baseline': {'start_date': None, 'target_date': None,
                     'target_event_id': None, 'rebaselined_at': None,
                     'rebaselines': 0},
        'created_by': acting_member.get('id')})
    source = curated.get('source') or {}
    n = len(curated.get('phases') or [])
    tail = ("Nothing's claimed yet: see the footprint and approve it on the "
            "Programs page.")
    # The three tiers, said out loud. Saying "hand-written" for all of them
    # was wrong twice over: nothing had been written, and a research outage
    # read exactly like the web having nothing on the aim.
    origin = source.get('origin') or (
        'none' if source.get('hand_written') else 'cited')
    if origin == 'cited':
        plan = source.get('plan_name') or 'what was found'
        msg = f"Proposed \"{title}\" with a {n}-phase plan from {plan}. {tail}"
    elif origin == 'generated':
        msg = (f"Proposed \"{title}\". No published program fit it, so I "
               f"made a {n}-phase plan and it's labelled as mine rather than "
               f"anyone's real curriculum. {tail}")
    else:
        why = source.get('why_this_one') or 'no plan could be found'
        msg = (f"Proposed \"{title}\" with practice time but no plan — "
               f"{why}. {tail}")
    return {"status": "success", "id": pid, "message": msg}


def log_program_session(program_title: str, minutes: int = None,
                        acting_member: dict = None) -> Dict[str, Any]:
    """The person practising says so — a kid reporting their own guitar
    session is the point (wraps `services.programs.log_session`, which only
    ever counts up). Logging on somebody ELSE's program needs a
    parent/adult, same rule as every other program write."""
    refusal = _program_writer(acting_member, 'log a session')
    if refusal:
        return refusal
    row, rows = _match_program(program_title, acting_member)
    if not row:
        titles = ', '.join(p.get('title') or '?' for p in rows[:8]) or 'no programs yet'
        return {"status": "error",
                "message": f"I couldn't pin down '{program_title}'. Programs: {titles}."}
    refusal = _program_owns_or_parent(acting_member, row, 'log a session')
    if refusal:
        return refusal
    from services import programs as _prog
    return _prog.log_session(row['id'], minutes=minutes, source='added')


def negotiate_day(day: str = None, event_title: str = None,
                  acting_member: dict = None) -> dict:
    """What would make a broken day work. Read-only — it never asks anybody.

    Reads need a resolved member: this names who in the family would have to
    give something up, and that is not a sentence for an anonymous wall panel.
    """
    from services import negotiation, storage as _st
    if not acting_member:
        return {'status': 'error',
                'message': "I need to know who's asking before I can look at "
                           "who'd have to give something up."}
    # The model says "Tuesday" or "tomorrow", not an ISO date. Handed straight
    # to the day cache that misses, and a miss here reads as "nothing on
    # Tuesday needs a deal — it all covers": a confident all-clear on the exact
    # question this tool exists to answer.
    date_str = _parse_fuzzy_date(day).isoformat()
    cache = _st.get_cached_daily_schedule(date_str) or {}
    sched = cache.get('schedule') or {}
    broken = list(sched.get('true_unassigned') or [])
    if event_title:
        wanted = event_title.strip().lower()
        events = {str(e.get('id')): e for e in (sched.get('events') or [])}
        broken = [b for b in broken
                  if wanted in (events.get(str(b), {}).get('title') or '').lower()]
    if not broken:
        return {'status': 'success',
                'message': f"Nothing on {date_str} needs a deal — it all covers."}
    seeds = broken[:3]
    # The deep budget is for ONE question a person is waiting on. Spent per
    # seed it becomes three of them -- up to 120 CP-SAT replays inside a 120 s
    # Assist budget, from a single chat turn. Divided, the turn costs what one
    # deep search costs however many uncovered events the day has.
    budget = max(1, int(_st.get_settings().get(
        'negotiation_deep_budget', negotiation.DEEP_BUDGET)) // len(seeds))
    deals = []
    for ev_id in seeds:
        deal = negotiation.propose(date_str, str(ev_id), budget=budget)
        if deal:
            deals.append({'deal_id': deal['id'], 'line': deal['line'],
                          'people': deal.get('cost', {}).get('people')})
    if not deals:
        return {'status': 'success',
                'message': "I looked, and nothing I can change makes that day "
                           "work. It needs an outside hand or a skip."}
    lines = '\n'.join(f"• {d['line']}" for d in deals)
    return {'status': 'success', 'deals': deals,
            'message': f"Here's what would work:\n{lines}\n\nSay the word and "
                       f"I'll ask them."}


def ask_deal(event_title: str, day: str = None, acting_member: dict = None) -> dict:
    """Send a found deal's asks. A person's decision, never the model's.

    An ALLOWLIST, not a blocklist: /api/chat is WALL_OR_SERVICE, so an
    unresolved caller must be refused rather than walked through a role check
    with role None.

    Matched on the title AND the day. A title alone is not an identifier: a
    weekly practice has a draft deal on two different evenings often enough,
    and "ask them about Soccer" fanning asks at the wrong Tuesday is worse
    than a question. Two candidates and no day given means asking WHICH,
    never guessing.
    """
    from services import negotiation, storage as _st
    if not acting_member or acting_member.get('role') not in ('parent', 'adult'):
        return {'status': 'error',
                'message': "Asking the family to rearrange their evening is a "
                           "grown-up's call — it needs a parent or an adult."}
    wanted = (event_title or '').strip().lower()
    if not wanted:
        return {'status': 'error', 'message': "Which day's deal?"}
    matches = [d for d in _st.get_deals(state='draft')
               if wanted in (d.get('seed_title') or '').lower()]
    if day:
        date_str = _parse_fuzzy_date(day).isoformat()
        matches = [d for d in matches if str(d.get('date')) == date_str]
        if not matches:
            return {'status': 'error',
                    'message': f"I don't have a deal waiting for "
                               f"'{event_title}' on {date_str}."}
    if not matches:
        return {'status': 'error',
                'message': f"I don't have a deal waiting for '{event_title}'. "
                           f"Ask me to look for one first."}
    if len(matches) > 1:
        named = ', '.join(sorted({f"{d.get('seed_title') or 'that'} on "
                                  f"{d.get('date')}" for d in matches}))
        return {'status': 'error',
                'message': f"I have more than one deal matching "
                           f"'{event_title}' — {named}. Which one did you mean?"}
    return negotiation.start_asks(matches[0]['id'], acting_member.get('id'))


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
    chores = storage.get_offered_chores()   # an out-of-season chore cannot be claimed
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
    if _rewards_off():
        return dict(REWARDS_OFF)
    from services import storage
    # Switched-off and out-of-season goals are not on offer (services/seasons.py).
    goals = [r for r in storage.get_offered_rewards() if r.get('pooled')]
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
    if _rewards_off():
        return dict(REWARDS_OFF)
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
    goals = [r for r in storage.get_offered_rewards() if r.get('pooled')]
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
                           "create them on Schedule → Calendar → Status days."}
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
        # Upcoming items one per line; past-due ones fold into a single
        # count (they are mostly handed in on Canvas and never ticked here,
        # and listed oldest-first they buried what is due tomorrow). Asking
        # by name still finds them — complete_kid_task matches every open task.
        import main as _m
        tasks = storage.decorate_kid_tasks(storage.get_kid_tasks(member['id']))
        late = [t for t in tasks if (t.get('due_date') or '') < today.isoformat()]
        out = [_m._task_line(t, today) for t in tasks if t not in late]
        if late:
            out.append(f"🗂 {len(late)} still open from earlier"
                       + (f" (latest: {late[-1].get('title')})" if late[-1].get('title') else ""))
        return out

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

def _visible_shopping_lists(acting_member: dict = None) -> list:
    """Every list this speaker may know exists. Private lists (audience
    'private') belong only to their shared_with — and a caller with NO
    resolved member (HA voice satellite, admin dashboard chat) is a shared
    surface, which must not find the gift list either. Household lists pass
    for everyone: voice adds stay deliberately ungated (module note)."""
    from services import storage, scope
    return [l for l in storage.get_shopping_lists()
            if scope.audience_allows(l, 'shopping_list', acting_member)]


def _resolve_shopping_list(list_name: str = "", acting_member: dict = None) -> tuple:
    """(list, error_message). Falls back to the default list, which is created
    on first use so a fresh install never fails a voice add. Resolution runs
    over the lists the SPEAKER may see — a private list is unfindable, and
    unmentionable in the error text, for anybody off it."""
    from services import storage
    low = (list_name or '').strip().lower()
    if not low:
        return storage.ensure_default_shopping_list(), None
    lists = _visible_shopping_lists(acting_member)
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
    lst, err = _resolve_shopping_list(list_name, acting_member)
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
    lst, err = _resolve_shopping_list(list_name, acting_member)
    if err:
        return {"status": "error", "message": err}
    items = storage.get_shopping_items(lst['id'], include_checked=False)
    if not items:
        return {"status": "success",
                "message": f"{lst.get('name')} is empty — nothing needed."}
    # Split by shop RUN when there is more than one, because "what's on the
    # list" has two different answers when somebody is heading out mid-week for
    # the one thing tonight's re-planned dinner needs: what THIS trip is for,
    # and the big run's list, which they may or may not want to start on while
    # they are standing there. Asking is the point; assuming either way is not.
    from services import shopping as _shop
    try:
        groups = [g for g in _shop.item_runs(lst['id'])['groups'] if g['items']]
    except Exception:
        groups = []

    def _lines(rows):
        return "\n".join(f"• {i.get('name')}" + (f" ({i['qty']})" if i.get('qty') else "")
                         for i in rows)

    if len(groups) > 1:
        out = [f"{lst.get('name')} ({len(items)}), split by trip:"]
        for g in groups:
            out.append(f"\n{g['label']} ({len(g['items'])}):\n" + _lines(g['items']))
        return {"status": "success", "message": "\n".join(out)}
    return {"status": "success",
            "message": f"{lst.get('name')} ({len(items)}):\n" + _lines(items)}


def check_off_shopping_item(item_name: str, list_name: str = "",
                            acting_member: dict = None) -> Dict[str, Any]:
    """Check something off — the in-the-aisle path. Fuzzy match on open items."""
    from services import storage
    lst, err = _resolve_shopping_list(list_name, acting_member)
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
    lst, err = _resolve_shopping_list(list_name, acting_member)
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
    lst, err = _resolve_shopping_list(list_name, acting_member)
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
    # Week-aware: the voice answer and the Meals page are one question to the
    # family, so they must give one answer.
    plate = meals.showing_plate(day.isoformat(), plan)
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
        lst = next((l for l in _visible_shopping_lists(acting_member)
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
        lst = next((l for l in _visible_shopping_lists(acting_member)
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
                  whole_meals: bool = False,
                  max_servings: int = 1, window_days: int = 7,
                  dwell_days: int = 3, except_dishes: str = "",
                  acting_member: dict = None) -> Dict[str, Any]:
    """WRITE: how this household EATS. "we only eat meat about once a week",
    "takeout now and then", "we cook one kind of beans at a time and eat it a
    few days before making the next". `whole_meals` is structural like
    `takeout`: type='meal' is a field, so "one-pot dinners at most twice a
    week" needs no tagging campaign."""
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
                              types=['meal'] if whole_meals else [],
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


def _find_occasion(name: str, viewer: dict = None) -> Optional[dict]:
    """Family-network S4: filtered by audience BEFORE matching, so a kid
    asking Argyle about a surprise party gets "nothing on the books" — the
    same answer as a party that does not exist, which is the point (§13: no
    trace at all for one who may not know). A caller with no identity (admin
    dashboard, HA voice — identity on voice is the arc's open question #5)
    keeps today's behaviour."""
    from services import storage, scope
    low = (name or '').strip().lower()
    rows = storage.get_occasions(include_done=True)
    if viewer is not None:
        rows = [o for o in rows
                if scope.audience_allows(o, 'occasion', viewer)]
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
    25th to the 29th", "Ellie's birthday party is on the 14th".

    kind='invited' is for a party the family is GOING to rather than hosting
    ("Ellie's been invited to Jack's party on Saturday") — it asks about the
    present instead of the cooking, and keeps its gift list off the kids'
    screens."""
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
    o = _find_occasion(occasion_name, acting_member)
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
    o = _find_occasion(occasion_name, acting_member)
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
    o = _find_occasion(occasion_name, acting_member)
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
    o = _find_occasion(occasion_name, acting_member)
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
    o = _find_occasion(occasion_name, acting_member)
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
    o = _find_occasion(occasion_name, acting_member)
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


def suggest_gift_ideas(occasion_name: str, extra: str = "",
                       acting_member: dict = None) -> Dict[str, Any]:
    """READ: "what should we get Jack for his party?", "any present ideas for
    Saturday?"

    Never names a product on its own authority — it searches, and reports what
    a real shop actually stocks under the budget. Suggesting only; picking is
    a tap on the occasion page, because a present is not a thing to have
    chosen for you by a chat message.
    """
    from services import occasions as _occ
    o = _find_occasion(occasion_name, acting_member)
    if not o:
        return {"status": "error",
                "message": f"I don't have an occasion called '{occasion_name}'."}
    res = _occ.gift_ideas(o['id'], extra)
    if res.get('error') and not res.get('queries'):
        return {"status": "error", "message": "I couldn't think of anything useful."}
    if not res.get('searched'):
        ideas = ', '.join(q['query'] for q in res.get('queries', [])[:5])
        return {"status": "success",
                "message": f"No shop search is set up, so these are things to look "
                           f"for rather than real products: {ideas}."}
    cands = res.get('candidates') or []
    if not cands:
        budget = res.get('budget')
        tail = f" under ${budget:g}" if budget else ""
        return {"status": "success",
                "message": f"I searched and found nothing good{tail}. "
                           "Worth raising the budget or telling me what they're into."}
    lines = '; '.join(
        f"{c['title']}" + (f" (${c['price']:g})" if c.get('price') else "")
        for c in cands[:4])
    more = f" and {len(cands) - 4} more" if len(cands) > 4 else ""
    return {"status": "success",
            "message": f"Found {len(cands)} for {o['title']}: {lines}{more}. "
                       "They're on the occasion page — pick the ones you like "
                       "and they'll go on a private list ready for a cart."}


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
        plate = meals.showing_plate(date_str, plan, settings)
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
    """Flight management for the router. Thin wrapper over the validated
    registry handlers (generation, dedup, trip-day ordinals, draft-safe
    messages) so the router and the action buttons share one implementation."""
    action = (action or "generate").lower()
    args = {"event_id": trip_id}
    if isinstance(flight, dict):
        args.update(flight)

    if action == "generate":
        res = handle_generate_trip_flights({"event_id": trip_id, "prompt": prompt or ""})
    elif action == "add":
        res = handle_add_trip_flight(args)
    elif action == "edit":
        res = handle_edit_trip_flight(args)
    elif action == "delete":
        res = handle_delete_trip_flight(args)
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
            "name": "decide_optional_event",
            "description": "Records whether the family is attending an OPTIONAL event's occurrence on a date: 'she's going to open gym today' -> attend, 'skip gymnastics tonight' -> skip, 'never mind, leave it open' -> clear. attend makes it a firm commitment (a driver will be found or a real alarm raised); skip takes it out of the day's plan with nobody scheduled or chased. Only works on events already marked optional.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the event or a substring of it."},
                    "target_date": {"type": "string", "description": "The date of the occurrence as YYYY-MM-DD (relative terms like 'today' or 'tomorrow' are accepted). Default today."},
                    "decision": {"type": "string", "enum": ["attend", "skip", "clear"], "description": "attend = going for sure; skip = not going today; clear = undecided again (goes if it fits)."}
                },
                "required": ["event_name", "decision"]
            }
        },
        {
            "name": "set_event_optional",
            "description": "Marks an event as OPTIONAL ('open gym is optional', 'we don't have to go to swim') or firm again ('practice is mandatory now'). Optional events are scheduled when the day allows but dropped first on conflicts, with calm messaging instead of no-driver alarms. Applies to the whole recurring series by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the event or a substring of it."},
                    "target_date": {"type": "string", "description": "A date the event occurs on, YYYY-MM-DD or relative ('today', 'Thursday'), used to find it. Default today."},
                    "optional": {"type": "boolean", "description": "true to mark optional (default), false to make it a firm commitment again."},
                    "scope": {"type": "string", "enum": ["series", "instance"], "description": "series (default) = every occurrence; instance = only the one on target_date."}
                },
                "required": ["event_name"]
            }
        },
        {
            "name": "group_events_ride_together",
            "description": "Groups specific events on ONE day to ride together ('Ava's swim and Ben's dive can go together', 'put both kids in the car for swim and dive'): one driver takes all of them, they never count as a conflict, and the route is one trip with no drive home in between. That day's occurrences only -- other weeks are untouched; it is not a rule. Parents/adults only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_names": {"type": "array", "items": {"type": "string"}, "description": "Two or more event names (or substrings), all on target_date. The last is the event the others join."},
                    "target_date": {"type": "string", "description": "The day of the occurrences as YYYY-MM-DD (relative terms like 'today' or 'tomorrow' are accepted). Default today."}
                },
                "required": ["event_names"]
            }
        },
        {
            "name": "ungroup_event",
            "description": "Takes one event out of its ride-together group ('swim doesn't ride with dive anymore'). A group left with one event dissolves. Parents/adults only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the event or a substring of it."},
                    "target_date": {"type": "string", "description": "The date of the occurrence. Default today."}
                },
                "required": ["event_name"]
            }
        },
        {
            "name": "cancel_event",
            "description": "Cancels ONE occurrence of a calendar event ('practice is canceled', 'call off swim tomorrow — coach is sick'). Records it with the reason, marks the Google event CANCELED, and pushes the assigned driver and the kids. Nothing is deleted — the event stays on the calendar struck through, and can be restored. Parents/adults only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the event or a substring of it."},
                    "target_date": {"type": "string", "description": "The date of the occurrence, YYYY-MM-DD or relative ('today', 'tomorrow'). Default today."},
                    "reason": {"type": "string", "description": "Why it was canceled ('coach is sick', 'field flooded') — rides the pushes and the record."}
                },
                "required": ["event_name"]
            }
        },
        {
            "name": "restore_event",
            "description": "Un-cancels a previously canceled event occurrence ('practice is back on') — restores the Google title, re-plans the drive, tells everyone it is happening after all. Parents/adults only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the event or a substring of it."},
                    "target_date": {"type": "string", "description": "The date of the occurrence. Default today."}
                },
                "required": ["event_name"]
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
            "name": "make_request",
            "description": "Raises an ASK that somebody has to answer yes or no — 'can you get me at 3 instead of 4?', 'can somebody take the dentist call?', 'can you cover Thursday evening?'. Use this whenever the speaker wants something from another person rather than stating a fact. The asker is told the moment there's an answer, and an unanswered ask says so rather than fading away.",
            "parameters": {
                "type": "object",
                "properties": {
                    "body": {"type": "string", "description": "The ask, in the speaker's own words."},
                    "to_member": {"type": "string", "description": "Who they're asking. Omit to ask whichever adult can say yes."},
                    "kind": {"type": "string", "description": "ride_change | pickup_early | swap_drive | take_task | cover | permission | other"},
                    "about": {"type": "string", "description": "What it's about, if it names an existing task or drive — accepting then performs the change."}
                },
                "required": ["body"]
            }
        },
        {
            "name": "get_requests",
            "description": "Reads what's waiting for an answer — both directions ('is anyone waiting on me?', 'did anyone answer me?').",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "answer_request",
            "description": "Says yes or no to somebody's ask ('yes, tell her I'll get her at 3', 'no, I'm in a meeting until 5'). Declining with a reason is a real answer and better than silence — always pass the reason when one was given.",
            "parameters": {
                "type": "object",
                "properties": {
                    "accept": {"type": "boolean", "description": "True for yes, false for no."},
                    "which": {"type": "string", "description": "Which ask, if more than one is waiting (match on words or who asked)."},
                    "reason": {"type": "string", "description": "Why not — pass it whenever they said."}
                },
                "required": ["accept"]
            }
        },
        {
            "name": "add_household_task",
            "description": "Adds household work that has a DEADLINE BUT NO DESTINATION — 'sign the permission slip', 'call the pediatrician', 'renew the passports', '$12 for picture day', 'book the dentist'. If the job is to GO somewhere, use add_errand instead (that one is a drive the solver routes). Leave it unassigned unless somebody was named: 'the household owes this' is a real state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The task, in the family's own words."},
                    "due": {"type": "string", "description": "When it's due, as spoken ('Friday', 'the 14th'). Omit if there is no deadline."},
                    "assign_to": {"type": "string", "description": "Who is doing it, if anyone was named. Omit to leave it on the household."},
                    "notes": {"type": "string", "description": "Anything else that matters."},
                    "recurrence": {"type": "string", "description": "none | daily | weekly | monthly | yearly. Use yearly for inspections, physicals, passports, registration windows."},
                    "category": {"type": "string", "description": "paperwork | health | money | home | school | general"}
                },
                "required": ["title"]
            }
        },
        {
            "name": "get_household_tasks",
            "description": "Reads the household's task list ('what's on my plate?', 'what do we owe this week?', 'what's nobody doing?'). Use unassigned_only for the last one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "assigned_to": {"type": "string", "description": "Whose list to read. Omit for the whole household."},
                    "unassigned_only": {"type": "boolean", "description": "Only work nobody has taken."}
                },
                "required": []
            }
        },
        {
            "name": "complete_household_task",
            "description": "Marks a household task done ('I signed the permission slip', 'the passports are renewed'). A recurring task opens its next instance automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Which task, as spoken."}
                },
                "required": ["title"]
            }
        },
        {
            "name": "claim_household_task",
            "description": "Puts somebody's name on household work that nobody had taken ('I'll do the permission slip', 'give the dentist call to Dad'). This is the delegation path between adults.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Which task, as spoken."},
                    "member_name": {"type": "string", "description": "Who is taking it. Omit in driver chat to mean the speaker."}
                },
                "required": ["title"]
            }
        },
        {
            "name": "get_household_load",
            "description": "Who has been carrying the household lately — tasks done and drives driven ('who's been doing everything?', 'how's the split been this month?'). States it plainly and never scores it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How far back to look (default 30)."}
                },
                "required": []
            }
        },
        {
            "name": "cover_with_assist",
            "description": "Records that somebody OUTSIDE the family is handling a drive or one leg of it — a carpool parent, a neighbour ('Emma's mom is taking them to soccer today', 'Coach Dan is picking them up'). The covered work leaves the solver entirely: no family driver is scheduled and nobody is chased about it. Use leg for separate drop-off/pickup coverage. Use clear=true to take the selected work back.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The event being covered, as spoken ('soccer', 'the dance class')."},
                    "contact_name": {"type": "string", "description": "Who is covering it — their name OR what the family calls them ('Emma's mom'). Omit when clearing."},
                    "target_date": {"type": "string", "description": "Which day (default today). Accepts 'tomorrow', 'Friday'. For scope=series this is just the occurrence used to find the event."},
                    "leg": {"type": "string", "enum": ["dropoff", "pickup"], "description": "Which leg to hand over for a split drive. Omit only when the same person covers the whole drive."},
                    "clear": {"type": "boolean", "description": "True to hand the drive back to the family."},
                    "scope": {"type": "string", "enum": ["instance", "series"], "description": "instance (default) = only the occurrence on target_date. series = every occurrence of a recurring event, the standing arrangement ('Emma's mom has Tuesdays', 'they're taking soccer this season'). Do NOT use instance for an ongoing arrangement — it covers one day only."}
                },
                "required": ["event_name"]
            }
        },
        {
            "name": "get_assist_coverage",
            "description": "Reads what people outside the family are covering on a day, with their phone numbers ('who's driving soccer today?', 'what's the carpool this week?', 'what's Emma's mom's number?').",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Which day (default today)."}
                },
                "required": []
            }
        },
        {
            "name": "announce_to_room",
            "description": "Speaks a message OUT LOUD on the speaker in a named room of the house ('Lily is in the pool house, tell her it's time for dinner' -> room 'pool house'). Uses the room's voice satellite or media player via Home Assistant. Name the person it's for in recipient_name so they also get a written copy by DM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {"type": "string", "description": "The room as spoken ('pool house', 'garage'). Matched fuzzily against Home Assistant's areas and their aliases."},
                    "message": {"type": "string", "description": "The words to say out loud in that room."},
                    "recipient_name": {"type": "string", "description": "Which family member the message is for, if one was named (fuzzy matched). They get a DM copy too."},
                    "from_member": {"type": "string", "description": "Who is sending it, if they said. Omit in driver chat — the sender is already known."}
                },
                "required": ["room", "message"]
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
            "name": "list_open_findings",
            "description": "Lists what still needs a parent — drives with no driver, things waiting on an approval, decisions nobody has made ('what needs me?', 'anything outstanding?', 'what's still open?').",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "research_question",
            "description": "Looks something up on the web and answers with sources attached. Use for practical household questions the app cannot answer from its own data — local service pricing, whether a provider is licensed, what a good beginner course for something is, how a process works. Every fact returned names the page it came from.",
            "parameters": {"type": "object",
                           "properties": {"question": {"type": "string", "description": "The question, phrased as you would type it into a search engine."}},
                           "required": ["question"]}
        },
        {
            "name": "list_insights",
            "description": "Lists what Argyle's Mind has noticed about the family lately (the 'Argyle noticed' lane) — patterns, gentle observations, and things it's keeping an eye on.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "dismiss_insight",
            "description": "Dismisses one Mind insight by id after the user says they don't want it or it's not useful.",
            "parameters": {"type": "object",
                           "properties": {"insight_id": {"type": "string", "description": "The insight's id, from list_insights."}},
                           "required": ["insight_id"]}
        },
        {
            "name": "list_situations",
            "description": "What needs a person right now: uncovered rides, Argyle's observations, stalled threads, missions waiting on a decision, ranked, each with where it stands, the next step, and who has been asked so far ('what needs my attention?', 'anything I need to deal with?').",
            "parameters": {"type": "object",
                           "properties": {"kinds": {"type": "string", "description": "Optional comma list of finding,insight,thread,mission."},
                                          "limit": {"type": "integer", "description": "How many, default 10."}},
                           "required": []}
        },
        {
            "name": "next_situation",
            "description": "The ONE most pressing thing that needs a person, in a sentence, and it becomes the thing you are talking about: 'what needs my attention?', 'what's most urgent?', 'anything I need to deal with?'. Say skip_current for 'next', 'not that one', 'what else'. Use list_situations only for 'what's open', 'everything outstanding'.",
            "parameters": {"type": "object",
                           "properties": {"skip_current": {"type": "boolean", "description": "Move to the next one down the list."}},
                           "required": []}
        },
        {
            "name": "explain_situation",
            "description": "The full picture of one thing that needs a person: status, every option with its id, and the asks so far. Takes an id or a title fragment ('tell me about the Thursday soccer one'); with no ref it is the one we are talking about.",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string", "description": "The situation's id or a fragment of its title. Leave empty for the one we are talking about."},
                                          "kind": {"type": "string", "description": "Optional: finding|insight|thread|mission."}},
                           "required": []}
        },
        {
            "name": "act_on_situation",
            "description": "Do one of a situation's options: assign a driver, approve a step, set a thread's next step, answer a mission, snooze, dismiss, take it yourself, mark it handled, or say Argyle read a reply wrong (unread). 'Handle it' / 'do that' with no name means the one we are talking about. Use start_ask to ask somebody.",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string", "description": "Id or title fragment; empty for the one we are talking about."},
                                          "verb": {"type": "string", "enum": ["assign", "plan", "prepare", "do", "done", "skip", "research", "draft", "advance", "answer", "close", "snooze", "dismiss", "own", "unread", "release"]},
                                          "option_id": {"type": "string", "description": "The option id from explain_situation, when the verb has more than one."},
                                          "kind": {"type": "string"},
                                          "text": {"type": "string", "description": "For answer/draft/research: the text. For advance: the next action."},
                                          "next_action_at": {"type": "string", "description": "For advance: YYYY-MM-DD."}},
                           "required": ["verb"]}
        },
        {
            "name": "start_ask",
            "description": "Ask somebody for something about a situation, by a channel the person chose: 'text Sarah and ask her to drive Kate Thursday', 'email the inspector to come Friday', 'message Dad on Chauffeur'. With no ref it is about the one we are talking about. Returns the draft to copy (or sends it on Chauffeur).",
            "parameters": {"type": "object",
                           "properties": {"ref": {"type": "string", "description": "Empty for the one we are talking about."}, "to_name": {"type": "string"},
                                          "what": {"type": "string", "description": "The commitment being asked for, as a short phrase."},
                                          "channel": {"type": "string", "enum": ["chauffeur", "email", "text", "in_person"]},
                                          "kind": {"type": "string"}},
                           "required": ["to_name", "what", "channel"]}
        },
        {
            "name": "mark_ask_sent",
            "description": "The person says they sent the drafted text/email or asked in person ('sent it', 'I asked her'). With no ask_id it is the open ask on the one we are talking about.",
            "parameters": {"type": "object", "properties": {"ask_id": {"type": "string"}}, "required": []}
        },
        {
            "name": "answer_ask",
            "description": "Record what the person asked said ('Sarah said yes', 'Mike can't', 'she said no'), which applies the agreed change once. With no ask_id it is the open ask on the one we are talking about.",
            "parameters": {"type": "object",
                           "properties": {"ask_id": {"type": "string"}, "answer": {"type": "string", "enum": ["yes", "no"]}},
                           "required": ["answer"]}
        },
        {
            "name": "search_mail",
            "description": "Search the family's own mailbox for a thing's details: an order confirmation, a model number, a warranty, a school letter ('find the email about the dishwasher', 'what did the school send about the trip?'). Parent/adult only. Returns sender, date, subject and a snippet per hit; use read_mail for the whole message.",
            "parameters": {"type": "object",
                           "properties": {"query": {"type": "string", "description": "A few words to match in sender, subject or body."},
                                          "since_days": {"type": "integer", "description": "How far back, default 365."},
                                          "limit": {"type": "integer", "description": "How many, default 5, max 10."}},
                           "required": ["query"]}
        },
        {
            "name": "read_mail",
            "description": "Read one message from the family mailbox by the uid search_mail returned. Parent/adult only.",
            "parameters": {"type": "object", "properties": {"uid": {"type": "integer"}}, "required": ["uid"]}
        },
        {
            "name": "start_mission_for",
            "description": "Start getting something done that takes several steps with people or companies outside the family: 'get the dishwasher fixed', 'find someone to clean the gutters', 'sort out the permit'. Opens a thread and puts Argyle to work on it; Argyle comes back with questions and results. Nothing is booked, paid or sent without the person. Parent/adult only.",
            "parameters": {"type": "object",
                           "properties": {"goal": {"type": "string", "description": "What to get done, in the person's words."},
                                          "title": {"type": "string", "description": "A short name for the thread, if the person gave one."}},
                           "required": ["goal"]}
        },
        {
            "name": "list_threads",
            "description": "Lists open loops with somebody outside the family — a vendor callback, a permit still pending ('any open threads?', 'what's outstanding with the pest guy?', 'what's Ben carrying?'). Each one shows who owns it, what's next, and whether it's stalled.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "Filter by state: open, waiting, done, or dropped. Omit for all non-closed threads."},
                    "owner_name": {"type": "string", "description": "Filter to one family member's threads by name."},
                    "include_closed": {"type": "boolean", "description": "Include done/dropped threads. Default false."}
                },
                "required": []
            }
        },
        {
            "name": "create_thread",
            "description": "Opens a new thread for a promise somebody outside the family made that hasn't closed yet — a vendor callback, a permit application ('start a thread for the deck permit', 'the pest company is supposed to call back, track that'). Parent/adult only; the caller becomes the thread's owner.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "What the thread is about, e.g. 'Pest control' or 'Deck permit'."},
                    "goal": {"type": "string", "description": "What resolving this thread looks like, if said."},
                    "kind": {"type": "string", "description": "'vendor' or 'project'. Defaults to 'project'."},
                    "counterparty_name": {"type": "string", "description": "Who's on the other end, if not an existing contact."},
                    "counterparty_email": {"type": "string", "description": "Their email, if given."},
                    "next_action": {"type": "string", "description": "What has to happen next, if known."},
                    "next_action_at": {"type": "string", "description": "When the next action is due, as YYYY-MM-DD."}
                },
                "required": ["title"]
            }
        },
        {
            "name": "update_thread_action",
            "description": "Sets the next thing that has to happen on an existing thread, and when ('the county called back, next we need to schedule the inspection', 'push the pest thread to next Tuesday'). Parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_title": {"type": "string", "description": "The thread's title (fuzzy matched), e.g. 'Deck permit'."},
                    "next_action": {"type": "string", "description": "What has to happen next."},
                    "next_action_at": {"type": "string", "description": "When it's due, as YYYY-MM-DD."},
                    "note": {"type": "string", "description": "Anything worth logging alongside the change."}
                },
                "required": ["thread_title", "next_action"]
            }
        },
        {
            "name": "add_thread_note",
            "description": "Logs movement on a thread that isn't a change of plan — a call made, a voicemail left, a document received ('log that I left the pest company a voicemail'). Parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_title": {"type": "string", "description": "The thread's title (fuzzy matched)."},
                    "text": {"type": "string", "description": "What happened."},
                    "url": {"type": "string", "description": "A link worth attaching, if any."}
                },
                "required": ["thread_title", "text"]
            }
        },
        {
            "name": "draft_thread_message",
            "description": "Asks Argyle to propose the words for an email on a thread ('draft a follow-up to the pest company') and returns the draft as text. It NEVER sends anything and there is no tool that can — a person reviews, edits and sends the draft from the Threads page, so never promise the message will go out. Parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_title": {"type": "string", "description": "The thread's title (fuzzy matched)."},
                    "intent": {"type": "string", "description": "What the message should do, if said — e.g. 'ask when they can come back'."}
                },
                "required": ["thread_title"]
            }
        },
        {
            "name": "launch_mission",
            "description": "Starts a multi-step Argyle MISSION on an EXISTING thread the person names (thread_title): Argyle researches, compares and drafts over the next hour and brings back proposals a parent approves on the Missions page. For a NEW goal with no thread yet ('get the dishwasher fixed', 'find someone to fix the fence') use start_mission_for, which opens the thread too. Nothing is booked, sent or paid automatically — never promise it will be. Parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "What the mission should achieve."},
                    "thread_title": {"type": "string", "description": "Existing thread it belongs to, if the user named one (fuzzy matched)."}
                },
                "required": ["goal"]
            }
        },
        {
            "name": "close_thread",
            "description": "Ends a thread ('the pest thing is sorted, close it', 'drop the dresser thread — nobody wants it'). state must be 'done' (it resolved) or 'dropped' (it won't); ask which if unclear. Parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_title": {"type": "string", "description": "The thread's title (fuzzy matched)."},
                    "state": {"type": "string", "description": "'done' or 'dropped' — nothing else is accepted."}
                },
                "required": ["thread_title", "state"]
            }
        },
        {
            "name": "list_programs",
            "description": "Lists ambitions with a real plan attached — a curated curriculum, reserved practice time, a session log ('what programs are going?', 'what is Ben working on?'). Each shows who it's for, its state, the phase ahead, and sessions logged. A program is personal: without a name it defaults to the caller's own; naming someone else's is parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string", "description": "See one family member's programs by name, if said."}
                },
                "required": []
            }
        },
        {
            "name": "program_progress",
            "description": "How one program is going — sessions logged, minutes, milestones hit, the phase ahead ('how's guitar going?', 'how many sessions has Ben logged?'). Never a streak, a miss count, or a percentage — those numbers do not exist here on purpose.",
            "parameters": {
                "type": "object",
                "properties": {
                    "program_title": {"type": "string", "description": "The program's title (fuzzy matched), e.g. 'Guitar'."}
                },
                "required": ["program_title"]
            }
        },
        {
            "name": "propose_program",
            "description": "Proposes a new program: screens the aim, then finds a real cited plan for it ('I want to learn guitar', 'start Ben on a couch to 5k'). Refuses body-composition aims outright (weight, calories, BMI) for anyone, no exceptions. This ONLY proposes — nothing is claimed in the week. A person still has to see the footprint and approve it on the Programs page; there is no chat tool that does that. Proposing for yourself is open to anyone; naming someone else is parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The aim, e.g. 'learn guitar' or 'couch to 5k'."},
                    "for_member_name": {"type": "string", "description": "Whose program this is, if not the caller's own."},
                    "sessions_per_week": {"type": "integer", "minimum": 1, "maximum": 7, "description": "How many times a week to practise, 1-7. Defaults to 3."},
                    "minutes": {"type": "integer", "minimum": 5, "maximum": 240, "description": "Minutes per session, 5-240. Defaults to 25."},
                    "starting_point": {"type": "string", "description": "What they can already DO, in their own words ('already plays open chords', 'has a keyboard but no pedal', 'reads chapter books'). Makes the plan fit them instead of a generic beginner. Never a weight, a size or a calorie number - those are refused."}
                },
                "required": ["title"]
            }
        },
        {
            "name": "log_program_session",
            "description": "Logs that a practice session happened ('I practiced guitar today', 'log Ben's 5k session'). The count only ever goes up — there is no way to log a miss. Logging on your own program is open to anyone; someone else's is parent/adult only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "program_title": {"type": "string", "description": "The program's title (fuzzy matched)."},
                    "minutes": {"type": "integer", "description": "How long it ran, if said. Defaults to the program's usual session length."}
                },
                "required": ["program_title"]
            }
        },
        {
            "name": "negotiate_day",
            "description": "Works out what would make a broken day cover — whose event could move fifteen minutes, who could take a drive, what could be skipped ('can you make Tuesday work?', 'is there any way to cover Thursday?'). Read-only: it finds the deal, it does not ask anybody.",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "string", "description": "The day to work on — 'Tuesday', 'tomorrow', or YYYY-MM-DD. Defaults to today."},
                    "event_title": {"type": "string", "description": "Narrow to one uncovered event by title, if they named one."}
                },
                "required": []
            }
        },
        {
            "name": "ask_deal",
            "description": "Sends the asks for a deal that negotiate_day already found ('yes, ask them', 'go ahead and ask Lorena'). Parent/adult only. Nothing changes until every person asked has said yes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_title": {"type": "string", "description": "The uncovered event the deal is about, e.g. 'Soccer'."},
                    "day": {"type": "string", "description": "Which day's deal, if the same event has one on more than one day ('Tuesday', 'tomorrow', or YYYY-MM-DD)."}
                },
                "required": ["event_title"]
            }
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
            "description": "Records how this household EATS, as opposed to what it eats: we only eat meat about once a week, takeout is occasional, we cook one kind of beans at a time and eat it two or three days before making the next, don't repeat a takeout place within three weeks. Use kind=frequency_cap with max_servings and window_days for how often (counts the whole matched set), kind=batch_cycle with dwell_days for cook-a-batch-then-rotate, or kind=repeat_spacing with window_days for no-repeats (each matched dish individually cools down after being served). 'At most 2 takeout a week AND no repeats for 3 weeks' is TWO rules: one frequency_cap (max_servings=2, window_days=7, takeout=true) plus one repeat_spacing (window_days=21, takeout=true).",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "The rule in the family own words, e.g. meat about once a week."},
                    "kind": {"type": "string", "enum": ["frequency_cap", "batch_cycle", "repeat_spacing"], "description": "frequency_cap for how often (whole set); batch_cycle for cook one, eat it a few days, then the next; repeat_spacing for no-repeats (per-dish cooldown of window_days)."},
                    "tags": {"type": "string", "description": "Comma separated dish tags it applies to, e.g. meat or beans."},
                    "dish_names": {"type": "string", "description": "Comma separated specific dishes, when tags will not do."},
                    "takeout": {"type": "boolean", "description": "true when the rule is about takeout or delivery."},
                    "whole_meals": {"type": "boolean", "description": "true when the rule is about whole meals / one-pot dinners (dishes that are the entire plate on their own, like lasagna or chili)."},
                    "max_servings": {"type": "number", "description": "How many times, for frequency_cap."},
                    "window_days": {"type": "number", "description": "Per how many days for frequency_cap (7 = a week); the per-dish cooldown for repeat_spacing (21 = three weeks)."},
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
            "description": "Turns what an occasion needs into a real shopping list, scaled to the headcount: I need party favours for a shark party, we need decorations and paper plates. The list belongs to the occasion and goes to a cart from the Shopping & Lists page.",
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
            "name": "suggest_gift_ideas",
            "description": "Finds present ideas for a party the family was INVITED to, by searching a real shop and reporting what it actually stocks under the budget: what should we get Jack, any present ideas for Saturday. Never makes up a product or a price. Suggests only — picking happens on the occasion page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion_name": {"type": "string", "description": "Which party."},
                    "extra": {"type": "string", "description": "Anything the parent knows about the child, e.g. they are into dinosaurs."}
                },
                "required": ["occasion_name"]
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
# Admin tools — the scheduling-core, errand, memory, places and deep
# trip-planning tools. Schemas come from the registry's Pydantic models
# (get_openai_tools below); the router executes them through execute_tool.
# Admin context only — these are NEVER added to the PWA driver toolset, since
# a driver on the go must not reconfigure global scheduling.
# ---------------------------------------------------------------------------
ADMIN_TOOLS = [
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
SCHEDULE_MUTATING_ADMIN_TOOLS = {
    "add_routing_rule", "delete_routing_rule",
    "add_priority_rule", "delete_priority_rule",
    "run_solver",
    "add_errand", "update_errand", "delete_errand",
    "add_errand_rule", "delete_errand_rule",
    "manage_car",
}


def get_admin_tools() -> List[Dict]:
    """Registry schemas reshaped into the router's flat {name, description,
    parameters} format for the admin (non-driver) toolset. Pulled live from
    get_openai_tools() so the Pydantic models stay the single source of truth."""
    by_name = {t["function"]["name"]: t["function"] for t in get_openai_tools()}
    bridged = []
    for name in ADMIN_TOOLS:
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
        # The canonical first leg rides along so the toward-the-kid gate can
        # decide who hears: a voice-started drive with the kid aboard tells
        # only the other parent; a pickup slice tells the waiting kid too.
        _main._notify_kids_ride_started(ev["id"], leg_id=f"init_{ev['id']}")
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


# ==============================================================================
# REGISTRY — every tool by name: argument models, JSON schemas, dict-args
# handlers and execute_tool. This is what the router's admin toolset,
# chat_actions' action buttons and the missions catalogue read. Moved here
# verbatim from services/agent_tools.py (v1) on 2026-10-09 so there is one
# tool module; handlers that wrap the functions above now call them directly.
# ==============================================================================

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
    buffer_reason: Optional[str] = Field(default=None, description="For 'buffer' rules: why they arrive early, in the family's words ('Warm-up'). Shown to them, so never invented.")
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
    Do NOT use this for grouping events (use AddRoutingRuleTool with constraint_type='group' for a standing rule, or GroupEventsRideTogetherTool for one day's occurrences).
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

class ManageCarTool(BaseModel):
    """
    Creates, updates, or deletes a family car, or marks it unavailable (loaned out, in the shop).
    Cars limit who can drive which events: seat capacity, allowed drivers, and car-seat passenger
    restrictions. A driver listed on no car keeps an unrestricted personal car. Use action
    'set_unavailable' for things like 'the minivan is loaned to Aunt Sarah through Friday'.
    """
    action: str = Field(..., description="'create', 'update', 'delete', 'set_unavailable' (add an unavailability date range), or 'clear_unavailable' (remove all unavailability ranges).")
    car_id: str = Field("", description="Car id or exact car name. Required for every action except 'create'.")
    name: str = Field("", description="Car name, e.g. 'Minivan'. Required for 'create'.")
    seat_capacity: int = Field(0, description="Passenger seats excluding the driver. Defaults to 4 on create; 0 means 'leave unchanged' on update.")
    allowed_driver_ids: List[str] = Field(default=[], description="Driver IDs permitted to drive this car.")
    allowed_passenger_ids: List[str] = Field(default=[], description="Passenger IDs allowed to ride (car-seat restrictions). Empty means anyone fits.")
    default_driver_id: str = Field("", description="The driver who usually has this car; the solver avoids reassigning it away from them.")
    unavailable_start: str = Field("", description="For 'set_unavailable': first unavailable date (YYYY-MM-DD, inclusive).")
    unavailable_end: str = Field("", description="For 'set_unavailable': last unavailable date (YYYY-MM-DD, inclusive).")
    unavailable_reason: str = Field("", description="For 'set_unavailable': why, e.g. 'loaned to Aunt Sarah'.")

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

class ReopenChoreTool(BaseModel):
    """
    Puts a chore back in the pot (open, claimable now). Use when a verified chore needs doing again this period or to release a chore someone claimed but isn't doing. Chores finished and awaiting verification cannot be reopened.
    """
    chore_title: str = Field(..., description="The chore's name (fuzzy matched).")

class ChallengePetBattleTool(BaseModel):
    """
    Asks another family member for a pet battle on behalf of a child. Only
    ASKS -- the other person still has to accept, and the fight is always
    level-matched so it is never decided by who did more chores.
    """
    challenger_name: str
    opponent_name: str

class AwardPetXpTool(BaseModel):
    """
    Gives (or takes back) pet experience for a family member. Pet XP is a
    separate currency from chore points and can never become chore points.
    """
    member_name: str
    amount: int

class GetPetStatusTool(BaseModel):
    """
    Reports how somebody's pet critter is doing: its level, its element and
    how far it is from levelling up. There is no win-loss record to report.
    """
    member_name: Optional[str] = None

class GetPointBalancesTool(BaseModel):
    """
    Gets the current chore-point balance for every child, sorted highest first.
    """
    pass

class GetFamilyGoalsTool(BaseModel):
    """
    Lists the pooled 'family goal' rewards (like Family Movie Night) with how many points each child has pledged and how much is left to fund.
    """
    pass

class ContributeToFamilyGoalTool(BaseModel):
    """
    Pledges some of a child's points toward a pooled family-goal reward. Pledged points are held, not spent — a parent grants the goal once it's fully funded. Ask which child is pledging if unknown.
    """
    reward_title: str = Field(..., description="The family goal's name (fuzzy matched).")
    amount: int = Field(..., description="How many points to pledge.")
    member_name: str = Field(..., description="Which child is pledging.")

class AdjustPointsTool(BaseModel):
    """
    Adds, subtracts, or sets a child's chore points (a parent-level manual adjustment recorded in the points history). Use delta for relative changes ('give Bob 20 points' -> delta 20, 'take away 5' -> delta -5) or set_to for an absolute balance ('set Bob to 100'). Provide exactly one of delta / set_to.
    """
    member_name: str = Field(..., description="The child's name.")
    delta: Optional[int] = Field(default=None, description="Relative point change; negative to subtract.")
    set_to: Optional[int] = Field(default=None, description="Absolute target balance.")
    note: str = Field(default="", description="Short reason shown in the points history, e.g. 'Helped carry groceries'.")

class SendFamilyMessageTool(BaseModel):
    """
    Posts a message to the family chat channel everyone sees. The sender must be known: pass from_member with the speaker's name; if the speaker is unknown, ask who it is before sending.
    """
    message_text: str = Field(..., description="The message to post, in the sender's voice.")
    from_member: Optional[str] = Field(default=None, description="Who the message is from (family member name).")

class SendDirectMessageTool(BaseModel):
    """
    Sends a private direct message to one family member ('tell Mom I'll be late'). Sender must be known via from_member; ask if unknown.
    """
    recipient_name: str = Field(..., description="The family member to message (fuzzy matched by name).")
    message_text: str = Field(..., description="The message to send, in the sender's voice.")
    from_member: Optional[str] = Field(default=None, description="Who the message is from.")

class GetFamilyMessagesTool(BaseModel):
    """
    Reads the most recent messages from the family chat channel.
    """
    limit: int = Field(default=10, description="How many recent messages to read (max 25).")

class ListChoresTool(BaseModel):
    """
    Lists the family chore pot: open chores, who has claimed what, and what awaits parent verification.
    """
    pass

class ListOpenFindingsTool(BaseModel):
    """
    Lists what still needs a parent: drives with nobody assigned, things waiting on an approval, and decisions nobody has made yet.
    """
    pass

class ListInsightsTool(BaseModel):
    """
    Lists what Argyle's Mind has noticed about the family lately (the 'Argyle noticed' lane) — patterns, gentle observations, and things it's keeping an eye on.
    """
    pass

class DismissInsightTool(BaseModel):
    """
    Dismisses one Mind insight by id after the user says they don't want it or it's not useful.
    """
    insight_id: str = Field(..., description="The insight's id, from list_insights.")

class ListSituationsTool(BaseModel):
    """What needs a person right now, ranked, with status, next step and asks so far."""
    kinds: Optional[str] = Field(None, description="Optional comma list of finding,insight,thread,mission.")
    limit: Optional[int] = Field(10, description="How many, default 10.")

class NextSituationTool(BaseModel):
    """The one most pressing thing that needs a person, as a sentence; it becomes the thing being talked about."""
    skip_current: Optional[bool] = Field(False, description="Move to the next one down the list.")

class ExplainSituationTool(BaseModel):
    """The full picture of one situation: status, every option with its id, the asks so far."""
    ref: Optional[str] = Field('', description="The situation's id or a fragment of its title; empty for the one being talked about.")
    kind: Optional[str] = Field(None, description="Optional: finding|insight|thread|mission.")

class ActOnSituationTool(BaseModel):
    """Do one of a situation's options (not asking somebody: that is start_ask)."""
    ref: Optional[str] = Field('', description="Id or title fragment; empty for the one being talked about.")
    verb: str = Field(..., description="assign|plan|prepare|do|done|skip|research|draft|advance|answer|close|snooze|dismiss|own")
    option_id: Optional[str] = Field(None, description="The option id from explain_situation.")
    kind: Optional[str] = None
    text: Optional[str] = Field(None, description="For answer/draft/research: the text. For advance: the next action.")
    next_action_at: Optional[str] = Field(None, description="For advance: YYYY-MM-DD.")

class StartAskTool(BaseModel):
    """Ask somebody for something about a situation by a chosen channel; returns the draft."""
    ref: Optional[str] = ''
    to_name: str
    what: str = Field(..., description="The commitment being asked for, as a short phrase.")
    channel: str = Field(..., description="chauffeur|email|text|in_person")
    kind: Optional[str] = None

class MarkAskSentTool(BaseModel):
    """The person says they sent the drafted text/email or asked in person."""
    ask_id: Optional[str] = None

class AnswerAskTool(BaseModel):
    """Record what the person asked said; yes applies the agreed change once."""
    ask_id: Optional[str] = None
    answer: str = Field(..., description="yes|no")

class SearchMailTool(BaseModel):
    """Search the family's own mailbox for a thing's details; returns sender, date, subject, snippet per hit."""
    query: str = Field(..., description="A few words to match in sender, subject or body.")
    since_days: Optional[int] = Field(365, description="How far back.")
    limit: Optional[int] = Field(5, description="How many, max 10.")

class ReadMailTool(BaseModel):
    """Read one message from the family mailbox by uid."""
    uid: int

class StartMissionForTool(BaseModel):
    """Start getting something done with people or companies outside the family: opens a thread and a mission on it."""
    goal: str = Field(..., description="What to get done, in the person's words.")
    title: Optional[str] = Field(None, description="A short name for the thread, if given.")

class ListProgramsTool(BaseModel):
    """
    Lists ambitions with a real plan attached — a curated curriculum, reserved practice time, a session log. Each shows who it's for, its state, the phase ahead, and sessions logged.
    """
    member_name: Optional[str] = Field(default=None, description="See one family member's programs by name, if said.")

class ClaimChoreTool(BaseModel):
    """
    Claims an open chore for a family member ('Ben will take the dishes'). member_name is required; ask who is claiming if unknown.
    """
    chore_title: str = Field(..., description="The chore's name (fuzzy matched).")
    member_name: Optional[str] = Field(default=None, description="Who is claiming it.")

class NegotiateDayTool(BaseModel):
    """
    Works out what would make a broken day cover — whose event could move fifteen minutes, who could take a drive, what could be skipped. Read-only: it finds the deal, it does not ask anybody.
    """
    day: Optional[str] = Field(None, description="The day to work on — 'Tuesday', 'tomorrow', or YYYY-MM-DD. Defaults to today.")
    event_title: Optional[str] = Field(None, description="Narrow to one uncovered event by title.")

class GetRoutineStatusTool(BaseModel):
    """
    Checks a family member's daily routine progress and streak ('did Ben finish his routine?').
    """
    member_name: str = Field(..., description="Whose routine to check.")
    target_date: str = Field(default="today", description="Day to check (YYYY-MM-DD, 'today', 'yesterday').")

class PostWeeklyDigestTool(BaseModel):
    """
    Posts the 'Family Week in Review' WEEKLY stats digest (driving, activities, chores, rewards, routines) into the family chat right now — the on-demand resend of the weekly automatic post. NOT for a single day's schedule (that's get_drive_digest, which posts nothing).
    """
    pass

class GetKidTasksTool(BaseModel):
    """
    Reads a child's school/deadline list — homework, tests, things to bring. Read-only; omit member_name for all kids.
    """
    member_name: Optional[str] = Field(None, description="Which child's list; omit for all kids.")

class AddKidTaskTool(BaseModel):
    """
    Adds a task to a child's school/deadline list (homework, test, project, thing to bring). Direct action, not a calendar event.
    """
    title: str = Field(..., description="What's due, e.g. 'Math worksheet'.")
    due_date: str = Field(..., description="When it's due: 'tomorrow', a weekday name, or YYYY-MM-DD.")
    member_name: Optional[str] = Field(None, description="Which child.")
    kind: Optional[str] = Field(None, description="homework | test | project | bring | other")

class CompleteKidTaskTool(BaseModel):
    """
    Checks a task off a child's school list by fuzzy title match.
    """
    task_title: str = Field(..., description="The task to check off.")
    member_name: Optional[str] = Field(None, description="Which child.")

class AddShoppingItemsTool(BaseModel):
    """
    Adds one or more things to a family shopping list ("we're out of milk", "add eggs and butter", "put paper towels on the Costco list"). Direct action for anyone including children — a list item costs nothing and never needs approval. Not for errands or calendar events.
    """
    items: str = Field(..., description="What to add; comma- or 'and'-separated values are split into separate items.")
    list_name: Optional[str] = Field(None, description="Which list or store; omit for the default list.")

class GetShoppingListItemsTool(BaseModel):
    """
    Reads what is still needed on a shopping list ("what's on the grocery list?").
    """
    list_name: Optional[str] = Field(None, description="Which list or store; omit for the default list.")

class CheckOffShoppingItemTool(BaseModel):
    """
    Checks something off the shopping list because it is now in the cart ("got the milk"). Use while shopping; fuzzy match on open items.
    """
    item_name: str = Field(..., description="The item that was picked up.")
    list_name: Optional[str] = Field(None, description="Which list or store; omit for the default list.")

class RemoveShoppingItemTool(BaseModel):
    """
    Removes something from the shopping list entirely because it is no longer wanted ("take cilantro off the list"). NOT for items that were bought — use CheckOffShoppingItemTool for those.
    """
    item_name: str = Field(..., description="The item to remove.")
    list_name: Optional[str] = Field(None, description="Which list or store; omit for the default list.")

class SuggestDinnerTool(BaseModel):
    """
    Answers "what's for dinner?" by filtering the family's OWN meals against today's schedule (time at home, who eats in the car, allergies). Does not invent recipes and does not know what food is in the house.
    """
    target_date: Optional[str] = Field(None, description="Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD.")

class AddMealToRepertoireTool(BaseModel):
    """
    Adds one of the family's regular meals in their OWN WORDS — a bare name ("tacos") or a whole plate written out ("chicken, rice, beans black red or pinto, veggies, salad"). A short name, cook times, portability and components (including substitutable options) are all derived. Never ask for cook times or ingredients. A plate is ONE meal, not one per component.
    """
    name: str = Field(..., description="The family's description of the meal, verbatim — a name or a full plate.")

class AddMealIngredientsToListTool(BaseModel):
    """
    Puts a meal's fresh ingredients on the shopping list; staples the family always has are skipped.
    """
    meal_name: str = Field(..., description="Which meal from the repertoire.")
    list_name: Optional[str] = Field(None, description="Which list or store; omit for the default list.")

class MarkMealServedTool(BaseModel):
    """
    Records that the family had a meal ("we had tacos"), keeping the rotation honest. Adds it to the repertoire if missing.
    """
    meal_name: str = Field(..., description="What they ate.")

class GetTonightsPlateTool(BaseModel):
    """
    Answers "what's for dinner?" with the actual plate - entree, sides and any dessert - composed against today's schedule.
    """
    target_date: Optional[str] = Field(None, description="Which day: today (default), tomorrow, a weekday name, or YYYY-MM-DD.")

class SetMealRuleTool(BaseModel):
    """
    Records how this household EATS: meat about once a week, takeout occasionally, one kind of beans at a time for a few days.
    """
    description: str = Field(..., description="The rule in the family own words.")
    kind: Optional[str] = Field("frequency_cap", description="frequency_cap (how often, whole set), batch_cycle (one at a time), or repeat_spacing (no repeats: per-dish cooldown of window_days).")
    tags: Optional[str] = Field(None, description="Comma separated dish tags, e.g. meat or beans.")
    dish_names: Optional[str] = Field(None, description="Comma separated specific dishes.")
    takeout: Optional[bool] = Field(False, description="true when the rule is about takeout.")
    whole_meals: Optional[bool] = Field(False, description="true when the rule is about whole meals / one-pot dinners (a dish that is the entire plate, like lasagna or chili).")
    max_servings: Optional[int] = Field(1, description="How many times, for frequency_cap.")
    window_days: Optional[int] = Field(7, description="Per how many days (7 = a week); for repeat_spacing, the per-dish cooldown (21 = three weeks).")
    dwell_days: Optional[int] = Field(3, description="How many days one batch lasts.")
    except_dishes: Optional[str] = Field(None, description="Comma separated dishes the rule should NOT cover.")

class GetMealRulesTool(BaseModel):
    """
    Lists the household meal rules.
    """
    pass

class PlanSpecificDinnerTool(BaseModel):
    """
    Sets a specific dinner on a specific date and LOCKS it ("steak Monday for Mom's birthday", "Grandma is bringing dinner Tuesday").
    """
    target_date: str = Field(..., description="Which day: tomorrow, Monday, or YYYY-MM-DD.")
    dish_names: Optional[str] = Field(None, description="Comma separated dishes; omit if nobody here is cooking.")
    note: Optional[str] = Field(None, description="Why, e.g. Mom's birthday.")

class UnlockDinnerTool(BaseModel):
    """
    Releases a locked night back to the proposal engine.
    """
    target_date: str = Field(..., description="Which day.")

class PairDishesTool(BaseModel):
    """
    Records that dishes always come together ("brisket always comes with beans and fries"). Directed - the partners stay free to appear elsewhere.
    """
    dish_name: str = Field(..., description="The dish that brings the others.")
    partner_names: str = Field(..., description="Comma separated dishes that come with it.")
    exclusive: Optional[bool] = Field(False, description="true for 'X is only ever served with Y'.")

class AddOccasionTool(BaseModel):
    """
    Records a holiday, birthday, party or get-together ("Thanksgiving is on the 26th and my parents are here from the 25th to the 29th"). The window makes holiday dishes available without putting them on any plate.
    """
    title: str = Field(..., description="What to call it, e.g. Thanksgiving 2026.")
    anchor_date: str = Field(..., description="The day itself.")
    kind: Optional[str] = Field("gathering", description="thanksgiving|christmas|easter|birthday|party|gathering")
    window_start: Optional[str] = Field("", description="YYYY-MM-DD when guests arrive. Optional.")
    window_end: Optional[str] = Field("", description="YYYY-MM-DD when it ends. Optional.")
    dish_tags: Optional[str] = Field("", description="Comma separated repertoire tags this brings out.")

class GetOccasionTool(BaseModel):
    """
    Reads the state of a holiday or party - guests, headcount, lists and outstanding errands.
    """
    occasion_name: Optional[str] = Field("", description="Which one; omit for the next one coming up.")

class GetOccasionInsightsTool(BaseModel):
    """
    The judgement calls around a holiday or party that a checklist cannot make: who is carrying all the work, what is undecided and what waiting costs, the clearest day to act, deadlines that fall out of the food (thawing pushes back the buy date), and clashes between cooking and driving.
    """
    occasion_name: Optional[str] = Field("", description="Which one; omit for the next one coming up.")

class GetOccasionGapsTool(BaseModel):
    """
    Says what is still MISSING for a holiday or party - a diff against the usual shape of that kind of occasion and against last year's, ordered by how little time is left. Use whenever someone asks whether they have forgotten something.
    """
    occasion_name: Optional[str] = Field("", description="Which one; omit for the next one coming up.")

class SetOccasionAttendanceTool(BaseModel):
    """
    Records whether someone in the FAMILY is coming to an occasion ("Grandad is not coming to Thanksgiving this year"). Everyone in the household is assumed in except helpers. For people outside the family use add_occasion_guests.
    """
    occasion_name: str = Field(..., description="Which occasion.")
    who: str = Field(..., description="A family member's name.")
    coming: bool = Field(..., description="true if they are coming, false if not.")

class AddOccasionGuestsTool(BaseModel):
    """
    Adds people to an occasion's guest list ("the Wilsons are coming, there are four of them"). Allergies bind like a family member's.
    """
    occasion_name: str = Field(..., description="Which occasion.")
    who: str = Field(..., description="A name or a household.")
    headcount: Optional[int] = Field(1, description="How many people that is.")
    cannot_eat: Optional[str] = Field("", description="Comma separated allergies/avoidances.")

class SourceForOccasionTool(BaseModel):
    """
    Turns what an occasion needs into a real shopping list scaled to the headcount ("party favours for a shark party").
    """
    occasion_name: str = Field(..., description="Which occasion.")
    needed: str = Field(..., description="What they need, in their words.")

class SuggestGiftIdeasTool(BaseModel):
    """
    Finds present ideas for a party the family was INVITED to by searching a real shop, and reports what it actually stocks under the budget ("what should we get Jack?"). Never invents a product or a price.
    """
    occasion_name: str = Field(..., description="Which party.")
    extra: str = Field("", description="Anything known about the child, e.g. they are into dinosaurs.")

class GetRunSheetTool(BaseModel):
    """
    Works out when to start cooking and what goes on when, counting back from when the family eats ("when do I need to start on Thursday?", "what time does the turkey go in?"). Accounts for one oven at two temperatures and for how many people are cooking.
    """
    target_date: Optional[str] = Field("today", description="The night, e.g. today, Saturday, 2026-11-26.")
    serve_at: Optional[str] = Field("", description="Optional HH:MM to eat at; omit to use the family's own sitting.")

class SetHostingTool(BaseModel):
    """
    Records how many people are eating on a night and how many are cooking ("we are having twelve people on Saturday", "four of us are cooking Thursday"). Headcount multiplies hands-on work; cooks divide it. serving_for=0 clears it back to an ordinary night.
    """
    target_date: str = Field(..., description="The night, e.g. Saturday, tomorrow, or 2026-11-26.")
    serving_for: int = Field(..., description="Whole headcount including the family. 0 clears it.")
    cooks: Optional[int] = Field(0, description="How many people are cooking. 0 leaves it as is.")

class SetDishScopeTool(BaseModel):
    """
    Marks a dish as holiday and party food rather than everyday food, so it stops being suggested on ordinary nights ("turkey is only for holidays", "we only make deviled eggs for parties"). The dish stays pickable by hand and its leftovers still count.
    """
    dish_name: str = Field(..., description="Which dish, e.g. turkey.")
    occasion_only: Optional[bool] = Field(True, description="true for holiday/party only, false to return it to everyday.")

class SetDishCategoriesTool(BaseModel):
    """
    Corrects what a dish IS on the plate, using the family's own categories ("black beans are a protein, not just a starch", "spaghetti and meat sauce is a whole meal", "the chili serves eight"). A dish may belong to several categories and then fills whichever one the plate still needs, never two at once.
    """
    dish_name: str = Field(..., description="Which dish, e.g. black beans.")
    categories: Optional[str] = Field("", description="Comma-separated category names in the family's own words, e.g. 'protein, starches/carbs'.")
    whole_meal: Optional[bool] = Field(None, description="true if it is a whole dinner on its own.")
    serves: Optional[int] = Field(None, description="How many people it feeds.")
    whole_units: Optional[bool] = Field(None, description="true if made in indivisible whole units (a tray, a cake, a sheet pan).")

class UnpairDishesTool(BaseModel):
    """
    Removes a pairing between dishes.
    """
    dish_name: str = Field(..., description="Which dish.")
    partner_name: Optional[str] = Field(None, description="Which partner; omit to clear all pairings for that dish.")

class SetDishPrepTool(BaseModel):
    """
    Records prep done OUTSIDE the cook window and sets its reminder ("we soak the rice the night before", "the chicken marinates an hour first").
    """
    dish_name: str = Field(..., description="Which dish, e.g. rice or chicken.")
    action: str = Field(..., description="The verb: soak, marinate, thaw, take out of the freezer.")
    when: Optional[str] = Field("hours_before", description="night_before | hours_before | morning_of")
    hours: Optional[float] = Field(1.0, description="How many hours before dinner, when using hours_before.")

class ClearDishPrepTool(BaseModel):
    """
    Removes prep from a dish ("we don't soak the rice anymore").
    """
    dish_name: str = Field(..., description="Which dish.")
    action: Optional[str] = Field(None, description="Which step; omit to clear all prep for that dish.")

class GetPrepAheadTool(BaseModel):
    """
    Answers "is there anything I need to do tonight" / "do I need to soak anything" for tonight and tomorrow.
    """
    pass

class GetShoppingTripTool(BaseModel):
    """
    Answers "when are we going shopping" / "when is the grocery run" with the SCHEDULED trip and how many things are waiting.
    """
    list_name: Optional[str] = Field(None, description="Which list or store; omit for the default list.")

class ScheduleShoppingTripTool(BaseModel):
    """
    Creates a recurring shopping trip for a list ("schedule a grocery run", "add a weekly Costco run"). The solver then fits it into the week.
    """
    store: Optional[str] = Field(None, description="Where they shop, e.g. Kroger on Main St.")
    list_name: Optional[str] = Field(None, description="Which list; omit for the default list.")
    weekly: Optional[bool] = Field(True, description="true (default) for a standing weekly run, false for a one-off.")

class GetWeekDinnersTool(BaseModel):
    """
    Answers "what are we eating this week" / "what's the meal plan" / "what do I need to buy for" - every night in the span the next grocery run has to cover.
    """
    pass

class ApproveWeekDinnersTool(BaseModel):
    """
    The family approves the whole week ("that looks good", "plan the week"). Pins every night and puts the span's fresh ingredients on the shopping list.
    """
    pass

class ChangeTonightsPlateTool(BaseModel):
    """
    Adds or drops ONE dish for ONE evening ("we've got corn too", "no salad tonight"). Changes only that evening's plate; the family's list of what they cook is untouched.
    """
    dish_name: str = Field(..., description="Which dish, e.g. corn.")
    action: Optional[str] = Field(None, description="add (default) or remove.")
    target_date: Optional[str] = Field(None, description="Which day: today (default), tomorrow, a weekday name, or YYYY-MM-DD.")

class AddDishesTool(BaseModel):
    """
    Adds things the family COOKS to their repertoire, in their own words. Every alternative becomes its own dish, typed as a whole meal, entree, side or dessert. Not for what is being eaten tonight.
    """
    description: str = Field(..., description="Their description, verbatim.")

class RefineMealDishTool(BaseModel):
    """
    Answers a question about a vague part of a meal ("the potatoes are russet, roasted"), making that dish's cook time and shopping line accurate.
    """
    dish_name: str = Field(..., description="The vague dish, e.g. 'potatoes'.")
    detail: str = Field(..., description="What they said, e.g. 'russet, roasted'.")

class MarkLeftoversTool(BaseModel):
    """
    Records that food is ALREADY MADE for a day ("we're having leftovers tonight", "the rice is already made"), so the app stops holding cook time for work nobody will do and keeps those ingredients off the shopping list.
    """
    what: Optional[str] = Field(None, description="What the leftovers are, e.g. 'chili'. Omit for plain 'we have leftovers'.")
    target_date: Optional[str] = Field(None, description="Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD.")
    parts: Optional[str] = Field(None, description="Only if PART of a meal is left over, e.g. 'rice and beans'.")

class ClearLeftoversTool(BaseModel):
    """
    Undoes a leftovers note for a day ("actually we're cooking tonight").
    """
    target_date: Optional[str] = Field(None, description="Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD.")

class GetEatingPlanTool(BaseModel):
    """
    Answers "what's the plan for dinner?", "do we have time to cook tonight?", "who's eating when?" from the SCHEDULE: time at home to cook, whether the family eats in shifts, who eats in the car and by when their food must be ready, and whether anyone has no gap to eat. Does NOT know what food is in the house.
    """
    target_date: Optional[str] = Field(None, description="Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD.")

class SetHouseholdStatusTool(BaseModel):
    """
    Sets (or clears) a family status day — a pre-authored day type like 'Chemo Day' or 'Trip Day' ("today is a chemo day", "set rest day for tomorrow", "clear tomorrow's chemo day"). Setting it tells the kids in the family's own words and notifies the other adults. Day types are created on the Calendar page (Status days), not here.
    """
    protocol_name: str = Field(..., description="Which day type, e.g. 'Chemo Day' — fuzzy matched against the family's configured status day types.")
    target_date: Optional[str] = Field(None, description="Which day (or span start): 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD.")
    end_date: Optional[str] = Field(None, description="Optional span end for multi-day statuses ('Dad's away Tuesday through Friday') — same date formats. Omit for a single day.")
    note: Optional[str] = Field(None, description="Optional one-line 'today's different' nudge, e.g. 'rougher than usual'.")
    clear: Optional[bool] = Field(None, description="True to clear this status from that day instead of setting it (announces the change of plans).")

class GetHouseholdStatusTool(BaseModel):
    """
    Reads the family status for a day ("is tomorrow a chemo day?", "what's today's status?"). Read-only.
    """
    target_date: Optional[str] = Field(None, description="Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD.")

class GetDriveDigestTool(BaseModel):
    """
    Shows the drive digest for one day as a read-only answer (drives per driver sorted by time, prep-kit items, weather) — 'today's digest', 'the tomorrow digest', 'Friday's drives'. Never posts to any channel.
    """
    target_date: Optional[str] = Field(None, description="Which day: 'today' (default), 'tomorrow', a weekday name, or YYYY-MM-DD.")
    member_name: Optional[str] = Field(None, description="Limit to one family member's drives; omit for all drivers.")

class DecideOptionalEventTool(BaseModel):
    """
    Records whether the family is attending an OPTIONAL event's occurrence on a date: "she's going to open gym today" -> attend, "skip gymnastics tonight" -> skip, "leave it open" -> clear. attend makes it a firm commitment (a driver will be found or a real alarm raised); skip takes it out of the day's plan with nobody scheduled or chased. Only works on events already marked optional.
    """
    event_name: str = Field(..., description="The name of the event or a substring of it.")
    decision: str = Field(..., description="attend | skip | clear. attend = going for sure; skip = not going today; clear = undecided again (goes if it fits).")
    target_date: Optional[str] = Field("today", description="The date of the occurrence, YYYY-MM-DD or relative ('today', 'tomorrow').")

class SetEventOptionalTool(BaseModel):
    """
    Marks an event as OPTIONAL ("open gym is optional") or firm again ("practice is mandatory now"). Optional events are scheduled when the day allows but dropped first on conflicts, with calm messaging instead of no-driver alarms. Applies to the whole recurring series by default.
    """
    event_name: str = Field(..., description="The name of the event or a substring of it.")
    optional: bool = Field(True, description="true to mark optional, false to make it a firm commitment again.")
    scope: Optional[str] = Field("series", description="series (default) = every occurrence; instance = only the one on target_date.")
    target_date: Optional[str] = Field("today", description="A date the event occurs on, used to find it.")

class CancelEventTool(BaseModel):
    """
    Cancels ONE occurrence of a calendar event ("practice is canceled", "call off swim tomorrow — coach is sick"). Records it with the reason, marks the Google event CANCELED, and pushes the assigned driver and the kids. Nothing is deleted — the event stays on the calendar struck through, and can be restored. Parents/adults only.
    """
    event_name: str = Field(..., description="The name of the event or a substring of it.")
    target_date: Optional[str] = Field("today", description="The date of the occurrence, YYYY-MM-DD or relative ('today', 'tomorrow').")
    reason: Optional[str] = Field(None, description="Why it was canceled ('coach is sick') — rides the pushes and the record.")

class GroupEventsRideTogetherTool(BaseModel):
    """
    Groups specific event occurrences on ONE day to ride together ("Ava's swim and Ben's dive can go together", "put both kids in the car for swim and dive"): one driver takes all of them, they never count as a conflict, and the route is one trip with no drive home in between. Applies to that day's occurrences only -- other weeks are untouched. For a standing rule across weeks use AddRoutingRuleTool with constraint_type='group' instead. Parents/adults only.
    """
    event_names: List[str] = Field(..., description="Two or more event names (or substrings), all on target_date. The last one is the event the others join.")
    target_date: Optional[str] = Field("today", description="The day of the occurrences, YYYY-MM-DD or relative ('today', 'tomorrow').")

class UngroupEventTool(BaseModel):
    """
    Takes one event occurrence out of its ride-together group ("swim doesn't ride with dive anymore"). A group left with one event dissolves. Parents/adults only.
    """
    event_name: str = Field(..., description="The name of the event or a substring of it.")
    target_date: Optional[str] = Field("today", description="The date of the occurrence.")

class RestoreEventTool(BaseModel):
    """
    Un-cancels a previously canceled event occurrence ("practice is back on") — restores the Google title, re-plans the drive, tells everyone it is happening after all. Parents/adults only.
    """
    event_name: str = Field(..., description="The name of the event or a substring of it.")
    target_date: Optional[str] = Field("today", description="The date of the occurrence.")

class LaunchMissionTool(BaseModel):
    """Start a multi-step Argyle mission (research, compare, draft, propose).
    Parent/adult only. Nothing executes without human approval."""
    goal: str = Field(description="What the mission should achieve, in one sentence.")
    thread_title: Optional[str] = Field(None, description="Existing thread this belongs to, if any (fuzzy matched).")

class CreateThreadTool(BaseModel):
    """Opens a thread — a tracked open loop with someone OUTSIDE the family
    (a vendor, a company, a coach). Nothing is sent by opening it; messages
    are drafted on the thread later and a person reviews and sends them."""
    title: str = Field(description="Short name for the loop (e.g. \"Ana's Cleaning — biweekly service\").")
    goal: str = Field(default="", description="What done looks like.")
    kind: str = Field(default="vendor", description="'vendor' or 'project'.")
    counterparty_name: str = Field(default="", description="Who is on the other end.")
    counterparty_email: str = Field(default="", description="Their email, if known.")
    next_action: str = Field(default="", description="The first concrete move (e.g. 'send an intro email asking for a quote').")

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
    "manage_car": ManageCarTool.model_json_schema(),
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
    "challenge_pet_battle": ChallengePetBattleTool.model_json_schema(),
    "award_pet_xp": AwardPetXpTool.model_json_schema(),
    "get_pet_status": GetPetStatusTool.model_json_schema(),
    "get_point_balances": GetPointBalancesTool.model_json_schema(),
    "adjust_points": AdjustPointsTool.model_json_schema(),
    "get_family_goals": GetFamilyGoalsTool.model_json_schema(),
    "contribute_to_family_goal": ContributeToFamilyGoalTool.model_json_schema(),
    "reopen_chore": ReopenChoreTool.model_json_schema(),
    "send_family_message": SendFamilyMessageTool.model_json_schema(),
    "send_direct_message": SendDirectMessageTool.model_json_schema(),
    "get_family_messages": GetFamilyMessagesTool.model_json_schema(),
    "list_chores": ListChoresTool.model_json_schema(),
    "list_open_findings": ListOpenFindingsTool.model_json_schema(),
    "list_insights": ListInsightsTool.model_json_schema(),
    "dismiss_insight": DismissInsightTool.model_json_schema(),
    "list_situations": ListSituationsTool.model_json_schema(),
    "next_situation": NextSituationTool.model_json_schema(),
    "explain_situation": ExplainSituationTool.model_json_schema(),
    "act_on_situation": ActOnSituationTool.model_json_schema(),
    "start_ask": StartAskTool.model_json_schema(),
    "mark_ask_sent": MarkAskSentTool.model_json_schema(),
    "answer_ask": AnswerAskTool.model_json_schema(),
    "search_mail": SearchMailTool.model_json_schema(),
    "read_mail": ReadMailTool.model_json_schema(),
    "start_mission_for": StartMissionForTool.model_json_schema(),
    "list_programs": ListProgramsTool.model_json_schema(),
    "claim_chore": ClaimChoreTool.model_json_schema(),
    "negotiate_day": NegotiateDayTool.model_json_schema(),
    "get_routine_status": GetRoutineStatusTool.model_json_schema(),
    "post_weekly_digest": PostWeeklyDigestTool.model_json_schema(),
    "get_drive_digest": GetDriveDigestTool.model_json_schema(),
    "decide_optional_event": DecideOptionalEventTool.model_json_schema(),
    "set_event_optional": SetEventOptionalTool.model_json_schema(),
    "cancel_event": CancelEventTool.model_json_schema(),
    "restore_event": RestoreEventTool.model_json_schema(),
    "group_events_ride_together": GroupEventsRideTogetherTool.model_json_schema(),
    "ungroup_event": UngroupEventTool.model_json_schema(),
    "get_kid_tasks": GetKidTasksTool.model_json_schema(),
    "add_kid_task": AddKidTaskTool.model_json_schema(),
    "complete_kid_task": CompleteKidTaskTool.model_json_schema(),
    "set_household_status": SetHouseholdStatusTool.model_json_schema(),
    "get_household_status": GetHouseholdStatusTool.model_json_schema(),
    "add_shopping_items": AddShoppingItemsTool.model_json_schema(),
    "get_shopping_list_items": GetShoppingListItemsTool.model_json_schema(),
    "check_off_shopping_item": CheckOffShoppingItemTool.model_json_schema(),
    "remove_shopping_item_by_name": RemoveShoppingItemTool.model_json_schema(),
    "get_eating_plan": GetEatingPlanTool.model_json_schema(),
    "suggest_dinner": SuggestDinnerTool.model_json_schema(),
    "add_meal_to_repertoire": AddMealToRepertoireTool.model_json_schema(),
    "add_meal_ingredients_to_list": AddMealIngredientsToListTool.model_json_schema(),
    "mark_meal_served": MarkMealServedTool.model_json_schema(),
    "mark_leftovers": MarkLeftoversTool.model_json_schema(),
    "clear_leftovers": ClearLeftoversTool.model_json_schema(),
    "refine_meal_dish": RefineMealDishTool.model_json_schema(),
    "get_tonights_plate": GetTonightsPlateTool.model_json_schema(),
    "change_tonights_plate": ChangeTonightsPlateTool.model_json_schema(),
    "add_dishes": AddDishesTool.model_json_schema(),
    "get_week_dinners": GetWeekDinnersTool.model_json_schema(),
    "approve_week_dinners": ApproveWeekDinnersTool.model_json_schema(),
    "get_shopping_trip": GetShoppingTripTool.model_json_schema(),
    "set_meal_rule": SetMealRuleTool.model_json_schema(),
    "get_meal_rules": GetMealRulesTool.model_json_schema(),
    "plan_specific_dinner": PlanSpecificDinnerTool.model_json_schema(),
    "unlock_dinner": UnlockDinnerTool.model_json_schema(),
    "pair_dishes": PairDishesTool.model_json_schema(),
    "unpair_dishes": UnpairDishesTool.model_json_schema(),
    "set_dish_scope": SetDishScopeTool.model_json_schema(),
    "set_dish_categories": SetDishCategoriesTool.model_json_schema(),
    "set_hosting": SetHostingTool.model_json_schema(),
    "get_run_sheet": GetRunSheetTool.model_json_schema(),
    "add_occasion": AddOccasionTool.model_json_schema(),
    "get_occasion": GetOccasionTool.model_json_schema(),
    "get_occasion_gaps": GetOccasionGapsTool.model_json_schema(),
    "get_occasion_insights": GetOccasionInsightsTool.model_json_schema(),
    "add_occasion_guests": AddOccasionGuestsTool.model_json_schema(),
    "set_occasion_attendance": SetOccasionAttendanceTool.model_json_schema(),
    "source_for_occasion": SourceForOccasionTool.model_json_schema(),
    "suggest_gift_ideas": SuggestGiftIdeasTool.model_json_schema(),
    "set_dish_prep": SetDishPrepTool.model_json_schema(),
    "clear_dish_prep": ClearDishPrepTool.model_json_schema(),
    "get_prep_ahead": GetPrepAheadTool.model_json_schema(),
    "schedule_shopping_trip": ScheduleShoppingTripTool.model_json_schema(),
    "launch_mission": LaunchMissionTool.model_json_schema(),
    "create_thread": CreateThreadTool.model_json_schema(),
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
        "cars": storage.get_all_cars(),
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

def handle_manage_car(args: dict) -> dict:
    from services import storage
    action = (args.get("action") or "").strip().lower()
    cars = storage.get_all_cars()

    if action == "create":
        from models.schemas import Car
        car = Car(
            name=(args.get("name") or "").strip() or "Car",
            seat_capacity=int(args.get("seat_capacity") or 4),
            allowed_driver_ids=args.get("allowed_driver_ids") or [],
            allowed_passenger_ids=(args.get("allowed_passenger_ids") or None),
            default_driver_id=(args.get("default_driver_id") or None),
        )
        doc_id = storage.add_car(car.model_dump())
        return {"status": "success", "car_id": car.id, "doc_id": doc_id}

    needle = (args.get("car_id") or "").strip().lower()
    car = next((c for c in cars if str(c.get("id", "")).lower() == needle
                or (c.get("name") or "").strip().lower() == needle), None)
    if not car:
        known = ", ".join(f"{c.get('name')} ({c.get('id')})" for c in cars) or "none"
        return {"status": "error", "message": f"No car matching '{args.get('car_id')}'. Known cars: {known}"}
    doc_id = car["doc_id"]
    updated = {k: v for k, v in car.items() if k != "doc_id"}

    if action == "delete":
        storage.delete_car(doc_id)
        return {"status": "success", "deleted": car.get("name")}
    if action == "set_unavailable":
        if not args.get("unavailable_start") or not args.get("unavailable_end"):
            return {"status": "error", "message": "unavailable_start and unavailable_end (YYYY-MM-DD) are required"}
        updated["unavailable_ranges"] = (updated.get("unavailable_ranges") or []) + [{
            "start": args["unavailable_start"], "end": args["unavailable_end"],
            "reason": args.get("unavailable_reason") or ""}]
        storage.update_car(doc_id, updated)
        return {"status": "success", "car": updated["name"], "unavailable_ranges": updated["unavailable_ranges"]}
    if action == "clear_unavailable":
        updated["unavailable_ranges"] = []
        storage.update_car(doc_id, updated)
        return {"status": "success", "car": updated["name"], "unavailable_ranges": []}
    if action == "update":
        if (args.get("name") or "").strip():
            updated["name"] = args["name"].strip()
        if args.get("default_driver_id"):
            updated["default_driver_id"] = args["default_driver_id"]
        if int(args.get("seat_capacity") or 0) > 0:
            updated["seat_capacity"] = int(args["seat_capacity"])
        if args.get("allowed_driver_ids"):
            updated["allowed_driver_ids"] = args["allowed_driver_ids"]
        if args.get("allowed_passenger_ids"):
            updated["allowed_passenger_ids"] = args["allowed_passenger_ids"]
        storage.update_car(doc_id, updated)
        return {"status": "success", "car": updated}
    return {"status": "error", "message": f"Unknown action '{action}'. Use create/update/delete/set_unavailable/clear_unavailable."}

def handle_add_routing_rule(args: dict) -> dict:
    from services import storage
    args.setdefault('filter_sets', [])
    args.setdefault('buffer_before_mins', 0)
    args.setdefault('buffer_after_mins', 0)
    args.setdefault('buffer_reason', None)
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
    from services import maps, storage
    import time
    starts_on = args.get('starts_on', 0.0)
    if not starts_on: starts_on = time.time()
    errand = {
        'title': args.get('title'),
        'duration_mins': args.get('duration_mins', 30),
        'location': maps.resolve_routable_location(args.get('location')),
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
    if args.get('location'):
        from services import maps
        update_data['location'] = maps.resolve_routable_location(args.get('location'))
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

def handle_challenge_pet_battle(args: dict) -> dict:
    return challenge_pet_battle(args.get("challenger_name", ""),
                                args.get("opponent_name", ""))

def handle_award_pet_xp(args: dict) -> dict:
    return award_pet_xp(args.get("member_name", ""), args.get("amount", 0))

def handle_get_pet_status(args: dict) -> dict:
    return get_pet_status(args.get("member_name"))

def handle_get_point_balances(args: dict) -> dict:
    # Shared implementation with the v2 (Gemma router) stack so both agent
    # stacks stay in lockstep on chore-point behavior.
    return get_point_balances()

def handle_adjust_points(args: dict) -> dict:
    return adjust_points(args.get("member_name", ""),
                         delta=args.get("delta"), set_to=args.get("set_to"),
                         note=args.get("note", ""))

def handle_get_family_goals(args: dict) -> dict:
    return get_family_goals()

def handle_contribute_to_family_goal(args: dict) -> dict:
    return contribute_to_family_goal(args.get("reward_title", ""),
                                     args.get("amount"),
                                     member_name=args.get("member_name"))

def handle_reopen_chore(args: dict) -> dict:
    return reopen_chore(args.get("chore_title", ""))

def handle_send_family_message(args: dict) -> dict:
    return send_family_message(args.get("message_text", ""),
                               from_member=args.get("from_member"))

def handle_send_direct_message(args: dict) -> dict:
    return send_direct_message(args.get("recipient_name", ""),
                               args.get("message_text", ""),
                               from_member=args.get("from_member"))

def handle_get_family_messages(args: dict) -> dict:
    return get_family_messages(limit=args.get("limit", 10))

def handle_list_chores(args: dict) -> dict:
    return list_chores()

def handle_list_open_findings(args: dict) -> dict:
    return list_open_findings()

def handle_list_insights(args: dict) -> dict:
    # v1 loop runs only in admin contexts, so no acting-member gate needed;
    # member_role stays unset, which visible_insights treats like the wall
    # panel (no sensitive rows) — the safe default with no resolved identity.
    return list_insights()

def handle_dismiss_insight(args: dict) -> dict:
    # Same "admin-only context" reasoning as handle_post_weekly_digest: no
    # acting-member gate needed here.
    return dismiss_insight(args.get("insight_id") or "")

def _registry_parent() -> dict:
    # Registry WRITES (action buttons, mission proposals) run in admin
    # contexts; the parent of record stands in, as the admin surface's
    # approvals do.
    from services import storage
    return next((m for m in storage.get_all_members() if m.get('role') == 'parent'), None)

# Registry READS carry no person. They see what any adult sees (findings and
# plain insights) and never a parents-only row: a mission transcript is
# readable by adults.
_REGISTRY_READER = {'id': None, 'role': 'adult'}

def handle_list_situations(args: dict) -> dict:
    return list_situations(kinds=args.get('kinds'), limit=args.get('limit') or 10,
                           acting_member=_REGISTRY_READER)

def handle_next_situation(args: dict) -> dict:
    return next_situation(skip_current=bool(args.get('skip_current')), acting_member=_REGISTRY_READER)

def handle_explain_situation(args: dict) -> dict:
    return explain_situation(args.get('ref') or '', kind=args.get('kind'), acting_member=_REGISTRY_READER)

def handle_act_on_situation(args: dict) -> dict:
    return act_on_situation(args.get('ref') or '', args.get('verb') or '', option_id=args.get('option_id'),
                            kind=args.get('kind'), text=args.get('text'),
                            next_action_at=args.get('next_action_at'), acting_member=_registry_parent())

def handle_start_ask(args: dict) -> dict:
    return start_ask(args.get('ref') or '', args.get('to_name') or '', args.get('what') or '',
                     args.get('channel') or '', kind=args.get('kind'), acting_member=_registry_parent())

def handle_mark_ask_sent(args: dict) -> dict:
    return mark_ask_sent(args.get('ask_id') or '', acting_member=_registry_parent())

def handle_answer_ask(args: dict) -> dict:
    return answer_ask(args.get('ask_id') or '', args.get('answer') or '', acting_member=_registry_parent())

def handle_search_mail(args: dict) -> dict:
    # Registry context is the trusted admin/mission loop: the parent of record reads.
    return search_mail(args.get('query') or '', since_days=args.get('since_days') or 365,
                       limit=args.get('limit') or 5, acting_member=_registry_parent())

def handle_read_mail(args: dict) -> dict:
    return read_mail(int(args.get('uid') or 0), acting_member=_registry_parent())

def handle_start_mission_for(args: dict) -> dict:
    return start_mission_for(args.get('goal') or '', title=args.get('title'), acting_member=_registry_parent())

def handle_list_programs(args: dict) -> dict:
    # The v1 loop resolves no member and can produce no actor -- unlike
    # list_insights, list_programs REQUIRES one (a program is somebody's
    # personal ambition, not household-visible the way an insight's safe
    # default is), so this always comes back refused from this loop. It is
    # wired for parity with the catalog anyway, exactly as list_insights was
    # -- a read tool only, never a write, since a write here would have no
    # actor to attribute it to.
    return list_programs(member_name=args.get("member_name"))

def handle_claim_chore(args: dict) -> dict:
    return claim_chore(args.get("chore_title", ""),
                       member_name=args.get("member_name"))

def handle_negotiate_day(args: dict) -> dict:
    # The v1 loop is admin-only, so the caller is a grown-up by construction —
    # but negotiate_day gates on a resolved member, so give it the first parent
    # rather than None. `ask_deal` is deliberately absent from this registry:
    # fanning out asks needs an identity this loop cannot produce.
    from services import storage
    parents = [m for m in storage.get_all_members()
               if m.get('role') == 'parent' and not m.get('system')]
    return negotiate_day(day=args.get("day"),
                         event_title=args.get("event_title"),
                         acting_member=parents[0] if parents else None)

def handle_get_kid_tasks(args: dict) -> dict:
    return get_kid_tasks(args.get("member_name") or "")

def handle_add_kid_task(args: dict) -> dict:
    return add_kid_task(args.get("title") or "", args.get("due_date") or "",
                        member_name=args.get("member_name") or "",
                        kind=args.get("kind") or "other")

def handle_complete_kid_task(args: dict) -> dict:
    return complete_kid_task(args.get("task_title") or "",
                             member_name=args.get("member_name") or "")

def handle_add_shopping_items(args: dict) -> dict:
    return add_shopping_items(args.get("items") or "",
                              list_name=args.get("list_name") or "")

def handle_get_shopping_list_items(args: dict) -> dict:
    return get_shopping_list_items(args.get("list_name") or "")

def handle_check_off_shopping_item(args: dict) -> dict:
    return check_off_shopping_item(args.get("item_name") or "",
                                   list_name=args.get("list_name") or "")

def handle_remove_shopping_item(args: dict) -> dict:
    return remove_shopping_item_by_name(args.get("item_name") or "",
                                        list_name=args.get("list_name") or "")

def handle_suggest_dinner(args: dict) -> dict:
    return suggest_dinner(args.get("target_date") or "today")

def handle_add_meal_to_repertoire(args: dict) -> dict:
    return add_meal_to_repertoire(args.get("name") or "")

def handle_add_meal_ingredients_to_list(args: dict) -> dict:
    return add_meal_ingredients_to_list(args.get("meal_name") or "",
                                        list_name=args.get("list_name") or "")

def handle_mark_meal_served(args: dict) -> dict:
    return mark_meal_served(args.get("meal_name") or "")

def handle_get_tonights_plate(args: dict) -> dict:
    return get_tonights_plate(args.get("target_date") or "today")

def handle_set_meal_rule(args: dict) -> dict:
    # Keywords, not positions: the v2 signature grows (whole_meals landed
    # between takeout and max_servings) and a positional bridge silently
    # shifts every argument after the insertion point.
    return set_meal_rule(args.get("description") or "",
                         kind=args.get("kind") or "frequency_cap",
                         tags=args.get("tags") or "",
                         dish_names=args.get("dish_names") or "",
                         takeout=bool(args.get("takeout")),
                         whole_meals=bool(args.get("whole_meals")),
                         max_servings=int(args.get("max_servings") or 1),
                         window_days=int(args.get("window_days") or 7),
                         dwell_days=int(args.get("dwell_days") or 3),
                         except_dishes=args.get("except_dishes") or "")

def handle_get_meal_rules(args: dict) -> dict:
    return get_meal_rules()

def handle_plan_specific_dinner(args: dict) -> dict:
    return plan_specific_dinner(args.get("target_date") or "",
                                args.get("dish_names") or "",
                                args.get("note") or "")

def handle_unlock_dinner(args: dict) -> dict:
    return unlock_dinner(args.get("target_date") or "")

def handle_pair_dishes(args: dict) -> dict:
    return pair_dishes(args.get("dish_name") or "", args.get("partner_names") or "",
                       bool(args.get("exclusive")))

def handle_unpair_dishes(args: dict) -> dict:
    return unpair_dishes(args.get("dish_name") or "", args.get("partner_name") or "")

def handle_add_occasion(args: dict) -> dict:
    return add_occasion(args.get("title") or "", args.get("anchor_date") or "",
                        args.get("kind") or "gathering",
                        args.get("window_start") or "", args.get("window_end") or "",
                        args.get("dish_tags") or "")

def handle_get_occasion(args: dict) -> dict:
    return get_occasion(args.get("occasion_name") or "")

def handle_get_occasion_insights(args: dict) -> dict:
    return get_occasion_insights(args.get("occasion_name") or "")

def handle_get_occasion_gaps(args: dict) -> dict:
    return get_occasion_gaps(args.get("occasion_name") or "")

def handle_set_occasion_attendance(args: dict) -> dict:
    return set_occasion_attendance(args.get("occasion_name") or "",
                                   args.get("who") or "",
                                   bool(args.get("coming", True)))

def handle_add_occasion_guests(args: dict) -> dict:
    return add_occasion_guests(args.get("occasion_name") or "",
                               args.get("who") or "",
                               int(args.get("headcount") or 1),
                               args.get("cannot_eat") or "")

def handle_suggest_gift_ideas(args: dict) -> dict:
    return suggest_gift_ideas(args.get("occasion_name") or "",
                              args.get("extra") or "")

def handle_source_for_occasion(args: dict) -> dict:
    return source_for_occasion(args.get("occasion_name") or "",
                               args.get("needed") or "")

def handle_get_run_sheet(args: dict) -> dict:
    return get_run_sheet(args.get("target_date") or "today",
                         args.get("serve_at") or "")

def handle_set_hosting(args: dict) -> dict:
    return set_hosting(args.get("target_date") or "",
                       int(args.get("serving_for") or 0),
                       int(args.get("cooks") or 0))

def handle_set_dish_categories(args: dict) -> dict:
    return set_dish_categories(args.get("dish_name") or "",
                               args.get("categories") or "",
                               args.get("whole_meal"),
                               args.get("serves"),
                               args.get("whole_units"))

def handle_set_dish_scope(args: dict) -> dict:
    occ = args.get("occasion_only")
    return set_dish_scope(args.get("dish_name") or "",
                          True if occ is None else bool(occ))

def handle_set_dish_prep(args: dict) -> dict:
    return set_dish_prep(args.get("dish_name") or "", args.get("action") or "",
                         args.get("when") or "hours_before",
                         args.get("hours") or 1.0)

def handle_clear_dish_prep(args: dict) -> dict:
    return clear_dish_prep(args.get("dish_name") or "", args.get("action") or "")

def handle_get_prep_ahead(args: dict) -> dict:
    return get_prep_ahead()

def handle_get_shopping_trip(args: dict) -> dict:
    return get_shopping_trip(args.get("list_name") or "")

def handle_schedule_shopping_trip(args: dict) -> dict:
    return schedule_shopping_trip(args.get("store") or "",
                                  args.get("list_name") or "",
                                  args.get("weekly", True))

def handle_get_week_dinners(args: dict) -> dict:
    return get_week_dinners()

def handle_approve_week_dinners(args: dict) -> dict:
    return approve_week_dinners()

def handle_change_tonights_plate(args: dict) -> dict:
    return change_tonights_plate(args.get("dish_name") or "",
                                 action=args.get("action") or "add",
                                 target_date=args.get("target_date") or "today")

def handle_add_dishes(args: dict) -> dict:
    return add_dishes(args.get("description") or "")

def handle_refine_meal_dish(args: dict) -> dict:
    return refine_meal_dish(args.get("dish_name") or "", args.get("detail") or "")

def handle_mark_leftovers(args: dict) -> dict:
    return mark_leftovers(args.get("what") or "",
                          target_date=args.get("target_date") or "today",
                          parts=args.get("parts") or "")

def handle_clear_leftovers(args: dict) -> dict:
    return clear_leftovers(args.get("target_date") or "today",
                           what=args.get("what") or "")

def handle_get_eating_plan(args: dict) -> dict:
    return get_eating_plan(args.get("target_date") or "today")

def handle_get_drive_digest(args: dict) -> dict:
    return get_drive_digest(target_date=args.get("target_date") or "today",
                            member_name=args.get("member_name") or "")

def handle_post_weekly_digest(args: dict) -> dict:
    # v1 loop runs only in admin contexts, so no acting-member gate needed.
    return post_weekly_digest_now()

def handle_set_household_status(args: dict) -> dict:
    return set_household_status(args.get("protocol_name") or "",
                                target_date=args.get("target_date") or "today",
                                note=args.get("note") or "",
                                clear=bool(args.get("clear")),
                                end_date=args.get("end_date") or "")

def handle_get_household_status(args: dict) -> dict:
    return get_household_status(target_date=args.get("target_date") or "today")

def handle_get_routine_status(args: dict) -> dict:
    return get_routine_status(args.get("member_name", ""),
                              args.get("target_date", "today"))

def handle_decide_optional_event(args: dict) -> dict:
    from services import optional_events
    return optional_events.decide_by_title(args.get("event_name"),
                                           args.get("target_date") or "today",
                                           args.get("decision"))

def handle_set_event_optional(args: dict) -> dict:
    from services import optional_events
    return optional_events.set_optional_flag(args.get("event_name"),
                                             args.get("target_date") or "today",
                                             bool(args.get("optional", True)),
                                             args.get("scope") or "series")

def handle_cancel_event(args: dict) -> dict:
    # This stack serves the admin dashboard and HA voice — parent surfaces,
    # no resolved member — so the parent/adult gate passes on None.
    from services import cancellations
    return cancellations.cancel_by_title(args.get("event_name") or "",
                                         args.get("target_date") or "today",
                                         reason=args.get("reason") or "")

def handle_restore_event(args: dict) -> dict:
    from services import cancellations
    return cancellations.cancel_by_title(args.get("event_name") or "",
                                         args.get("target_date") or "today",
                                         restore=True)

def handle_group_events_ride_together(args: dict) -> dict:
    # Admin dashboard / HA voice: parent surfaces, so the gate passes on None
    # (same reasoning as handle_cancel_event).
    from services import ride_groups
    return ride_groups.group_by_titles(args.get("event_names") or [],
                                       args.get("target_date") or "today")

def handle_ungroup_event(args: dict) -> dict:
    from services import ride_groups
    return ride_groups.ungroup_by_title(args.get("event_name") or "",
                                        args.get("target_date") or "today")

def handle_launch_mission(args: dict) -> dict:
    # v1 loop is admin-only (dashboard/HA voice), so no acting-member gate is
    # needed here — same "trusted context" reasoning as handle_send_family_message
    # and handle_cancel_event. _member_id rides through as attribution only.
    from services import missions, storage as _st
    thread = None
    title = (args.get('thread_title') or '').strip()
    if title:
        thread = missions._match_thread(title)
    return missions.launch(args.get('goal') or '',
                           origin_kind='thread' if thread else 'chat',
                           origin_ref=thread['id'] if thread else None,
                           created_by=args.get('_member_id'),
                           tier='mission')

def handle_create_thread(args: dict) -> dict:
    # Reached only through the approve rail (a parent's tap) or the trusted
    # v1 contexts — opening a thread sends nothing; the threads page's
    # human-only Send is still the sole way words leave the house.
    from services import threads as _threads
    title = (args.get('title') or '').strip()
    if not title:
        return {"status": "error", "message": "The thread needs a title."}
    kind = (args.get('kind') or 'vendor').strip().lower()
    thread_id = _threads.create(
        title=title,
        owner_member_id=args.get('_member_id'),
        goal=(args.get('goal') or '').strip(),
        kind=kind if kind in ('vendor', 'project') else 'vendor',
        counterparty_name=(args.get('counterparty_name') or '').strip(),
        counterparty_email=(args.get('counterparty_email') or '').strip(),
        next_action=(args.get('next_action') or '').strip(),
        created_by=args.get('_member_id'))
    return {"status": "success", "id": thread_id,
            "message": f"Opened a thread: {title}."}

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
    "manage_car": handle_manage_car,
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
    "challenge_pet_battle": handle_challenge_pet_battle,
    "award_pet_xp": handle_award_pet_xp,
    "get_pet_status": handle_get_pet_status,
    "get_point_balances": handle_get_point_balances,
    "adjust_points": handle_adjust_points,
    "get_family_goals": handle_get_family_goals,
    "contribute_to_family_goal": handle_contribute_to_family_goal,
    "reopen_chore": handle_reopen_chore,
    "send_family_message": handle_send_family_message,
    "send_direct_message": handle_send_direct_message,
    "get_family_messages": handle_get_family_messages,
    "list_chores": handle_list_chores,
    "list_open_findings": handle_list_open_findings,
    "list_insights": handle_list_insights,
    "dismiss_insight": handle_dismiss_insight,
    "list_situations": handle_list_situations,
    "next_situation": handle_next_situation,
    "explain_situation": handle_explain_situation,
    "act_on_situation": handle_act_on_situation,
    "start_ask": handle_start_ask,
    "mark_ask_sent": handle_mark_ask_sent,
    "answer_ask": handle_answer_ask,
    "search_mail": handle_search_mail,
    "read_mail": handle_read_mail,
    "start_mission_for": handle_start_mission_for,
    "list_programs": handle_list_programs,
    "claim_chore": handle_claim_chore,
    "negotiate_day": handle_negotiate_day,
    "get_routine_status": handle_get_routine_status,
    "post_weekly_digest": handle_post_weekly_digest,
    "get_drive_digest": handle_get_drive_digest,
    "decide_optional_event": handle_decide_optional_event,
    "set_event_optional": handle_set_event_optional,
    "cancel_event": handle_cancel_event,
    "restore_event": handle_restore_event,
    "group_events_ride_together": handle_group_events_ride_together,
    "ungroup_event": handle_ungroup_event,
    "get_kid_tasks": handle_get_kid_tasks,
    "add_kid_task": handle_add_kid_task,
    "complete_kid_task": handle_complete_kid_task,
    "set_household_status": handle_set_household_status,
    "get_household_status": handle_get_household_status,
    "add_shopping_items": handle_add_shopping_items,
    "get_shopping_list_items": handle_get_shopping_list_items,
    "check_off_shopping_item": handle_check_off_shopping_item,
    "remove_shopping_item_by_name": handle_remove_shopping_item,
    "get_eating_plan": handle_get_eating_plan,
    "suggest_dinner": handle_suggest_dinner,
    "add_meal_to_repertoire": handle_add_meal_to_repertoire,
    "add_meal_ingredients_to_list": handle_add_meal_ingredients_to_list,
    "mark_meal_served": handle_mark_meal_served,
    "mark_leftovers": handle_mark_leftovers,
    "clear_leftovers": handle_clear_leftovers,
    "refine_meal_dish": handle_refine_meal_dish,
    "get_tonights_plate": handle_get_tonights_plate,
    "change_tonights_plate": handle_change_tonights_plate,
    "add_dishes": handle_add_dishes,
    "get_week_dinners": handle_get_week_dinners,
    "approve_week_dinners": handle_approve_week_dinners,
    "get_shopping_trip": handle_get_shopping_trip,
    "set_meal_rule": handle_set_meal_rule,
    "get_meal_rules": handle_get_meal_rules,
    "plan_specific_dinner": handle_plan_specific_dinner,
    "unlock_dinner": handle_unlock_dinner,
    "pair_dishes": handle_pair_dishes,
    "unpair_dishes": handle_unpair_dishes,
    "set_dish_scope": handle_set_dish_scope,
    "set_dish_categories": handle_set_dish_categories,
    "set_hosting": handle_set_hosting,
    "get_run_sheet": handle_get_run_sheet,
    "add_occasion": handle_add_occasion,
    "get_occasion": handle_get_occasion,
    "get_occasion_gaps": handle_get_occasion_gaps,
    "get_occasion_insights": handle_get_occasion_insights,
    "add_occasion_guests": handle_add_occasion_guests,
    "set_occasion_attendance": handle_set_occasion_attendance,
    "source_for_occasion": handle_source_for_occasion,
    "suggest_gift_ideas": handle_suggest_gift_ideas,
    "set_dish_prep": handle_set_dish_prep,
    "clear_dish_prep": handle_clear_dish_prep,
    "get_prep_ahead": handle_get_prep_ahead,
    "schedule_shopping_trip": handle_schedule_shopping_trip,
    "launch_mission": handle_launch_mission,
    "create_thread": handle_create_thread,
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
