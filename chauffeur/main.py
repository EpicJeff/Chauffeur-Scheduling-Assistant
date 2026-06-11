from fastapi import FastAPI, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any

class PushSubscription(BaseModel):
    driver_id: str
    subscription: Dict[str, Any]

class DriveStatus(BaseModel):
    leg_id: str
    status: str

import os
from py_vapid import Vapid, utils
from cryptography.hazmat.primitives import serialization

if os.path.exists('/data/options.json'):
    DATA_DIR = '/data'
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(DATA_DIR, exist_ok=True)

VAPID_PRIVATE_KEY_PATH = os.path.join(DATA_DIR, 'vapid_private.pem')
VAPID_PUBLIC_KEY_STR = ""

def ensure_vapid_keys():
    global VAPID_PUBLIC_KEY_STR
    v = Vapid()
    if not os.path.exists(VAPID_PRIVATE_KEY_PATH):
        print("Generating new VAPID keys...")
        v.generate_keys()
        v.save_key(VAPID_PRIVATE_KEY_PATH)
    else:
        v = Vapid.from_file(VAPID_PRIVATE_KEY_PATH)
    
    # Extract public key as URL-safe base64
    raw_pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    VAPID_PUBLIC_KEY_STR = utils.b64urlencode(raw_pub)
    if isinstance(VAPID_PUBLIC_KEY_STR, bytes):
        VAPID_PUBLIC_KEY_STR = VAPID_PUBLIC_KEY_STR.decode('utf-8')

ensure_vapid_keys()

from models.schemas import Driver, Rule, Settings, PriorityRule, ManualOverride, Passenger, TelemetryEvent
from services import storage, calendar, maps
from solver import matcher
from fastapi.templating import Jinja2Templates
from fastapi import Request
import asyncio
from contextlib import asynccontextmanager
from fastapi.responses import RedirectResponse
from fastapi.encoders import jsonable_encoder
import os
import uvicorn
from datetime import datetime, timedelta

async def poll_schedule():
    while True:
        try:
            await asyncio.to_thread(refresh_schedule_logic)
        except Exception as e:
            print(f"Polling error: {e}")
        await asyncio.sleep(300)

import time
from datetime import datetime, timezone
import json
import asyncio
import os
async def push_notification_loop():
    while True:
        try:
            from services import storage
            
            vapid_private_key = VAPID_PRIVATE_KEY_PATH
            if not os.path.exists(vapid_private_key):
                await asyncio.sleep(30)
                continue
                
            now_ts = datetime.now().timestamp()
            subs = storage.get_push_subscriptions()
            completed = storage.get_completed_drives()
            pending_notifications = storage.get_pending_notifications()
            
            for notif in pending_notifications:
                if notif.get("fired"): continue
                
                notif_id = notif["notif_id"]
                trigger_ts = notif["trigger_timestamp"]
                d_id = notif["driver_id"]
                
                # Check if it's time to fire (and hasn't expired > 10 mins ago)
                if trigger_ts <= now_ts <= trigger_ts + 600:
                    if notif_id not in completed:
                        send_push(d_id, subs, notif["title"], notif["body"], notif_id, notif.get("location"))
                    # Always mark it fired so we don't try again
                    storage.mark_notification_fired(notif_id)
                elif now_ts > trigger_ts + 600:
                    # Expired, mark it fired
                    storage.mark_notification_fired(notif_id)
                    
        except Exception as e:
            print(f"Error in push loop: {e}")
            
        await asyncio.sleep(30)

def send_push(d_id, subs, title, body, leg_id, location=None):
    from pywebpush import webpush, WebPushException
    import json
    import urllib.parse
    
    actions = [{"action": "complete", "title": "Mark Completed"}]
    navigate_url = None
    if location:
        navigate_url = f"/app?navigate_dest={urllib.parse.quote(location)}&navigate_title={urllib.parse.quote(title)}&navigate_leg={leg_id}"
        actions.insert(0, {"action": "navigate", "title": "Navigate"})

    for sub in subs:
        if sub.get("driver_id") == d_id:
            try:
                webpush(
                    subscription_info=sub["subscription"],
                    data=json.dumps({
                        "title": title, 
                        "body": body, 
                        "actions": actions, 
                        "data": {"leg_id": leg_id, "navigate_url": navigate_url}
                    }),
                    vapid_private_key=VAPID_PRIVATE_KEY_PATH,
                    vapid_claims={"sub": "mailto:admin@example.com"}
                )
                print(f"Sent push to {d_id}: {title} - {body}")
            except Exception as ex:
                print(f"Push failed: {repr(ex)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_schedule())
    push_task = asyncio.create_task(push_notification_loop())
    yield
    task.cancel()
    push_task.cancel()

app = FastAPI(title="Family Driver Graph Scheduler", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- UI Routes ---
@app.get("/")
def root_redirect():
    return RedirectResponse(url="dashboard")

@app.get("/dashboard")
def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")

@app.get("/app")
def driver_app(request: Request):
    return templates.TemplateResponse(request=request, name="app.html")

@app.get("/config")
def config(request: Request):
    return templates.TemplateResponse(request=request, name="config.html")

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# --- Drivers API ---
@app.get("/api/drivers")
def get_drivers():
    return storage.get_all_drivers()

@app.post("/api/drivers")
def create_driver(driver: Driver):
    doc_id = storage.add_driver(driver.model_dump() if hasattr(driver, 'model_dump') else driver.dict())
    refresh_schedule_logic()
    return {"doc_id": doc_id, "status": "created"}

@app.delete("/api/drivers/{doc_id}")
def delete_driver(doc_id: int):
    storage.delete_driver(doc_id)
    refresh_schedule_logic()
    return {"status": "deleted"}

# --- Passengers API ---
@app.get("/api/passengers")
def get_passengers():
    return storage.get_all_passengers()

@app.post("/api/passengers")
def create_passenger(passenger: Passenger):
    doc_id = storage.add_passenger(passenger.model_dump() if hasattr(passenger, 'model_dump') else passenger.dict())
    refresh_schedule_logic()
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/passengers/{doc_id}")
def update_passenger(doc_id: int, passenger: Passenger):
    storage.update_passenger(doc_id, passenger.model_dump() if hasattr(passenger, 'model_dump') else passenger.dict())
    refresh_schedule_logic()
    return {"status": "updated"}

@app.delete("/api/passengers/{doc_id}")
def delete_passenger(doc_id: int):
    storage.delete_passenger(doc_id)
    refresh_schedule_logic()
    return {"status": "deleted"}

# --- Rules API ---
@app.get("/api/rules")
def get_rules():
    return storage.get_all_rules()

@app.post("/api/rules")
def create_rule(rule: Rule):
    doc_id = storage.add_rule(rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    refresh_schedule_logic()
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/rules/{doc_id}")
def update_rule(doc_id: int, rule: Rule):
    storage.update_rule(doc_id, rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    refresh_schedule_logic()
    return {"status": "updated"}

@app.delete("/api/rules/{doc_id}")
def delete_rule(doc_id: int):
    storage.delete_rule(doc_id)
    refresh_schedule_logic()
    return {"status": "deleted"}

# --- Priority Rules API ---
@app.get("/api/priority_rules")
def get_priority_rules():
    return storage.get_all_priority_rules()

@app.post("/api/priority_rules")
def create_priority_rule(rule: PriorityRule):
    doc_id = storage.add_priority_rule(rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    refresh_schedule_logic()
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/priority_rules/{doc_id}")
def update_priority_rule(doc_id: int, rule: PriorityRule):
    storage.update_priority_rule(doc_id, rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    refresh_schedule_logic()
    return {"status": "updated"}

@app.delete("/api/priority_rules/{doc_id}")
def delete_priority_rule(doc_id: int):
    storage.delete_priority_rule(doc_id)
    refresh_schedule_logic()
    return {"status": "deleted"}

# --- Overrides API ---
@app.get("/api/overrides")
def get_overrides():
    return storage.get_all_overrides()

@app.post("/api/overrides")
def create_override(override: ManualOverride):
    doc_id = storage.add_override(override.model_dump() if hasattr(override, 'model_dump') else override.dict())
    refresh_schedule_logic()
    return {"doc_id": doc_id, "status": "created"}

@app.delete("/api/overrides/{doc_id}")
def delete_override(doc_id: int):
    storage.delete_override(doc_id)
    refresh_schedule_logic()
    return {"status": "deleted"}

@app.delete("/api/overrides/event/{event_id}")
def delete_override_by_event(event_id: str):
    # Overrides are unique per event_id, so we can use the same remove query as in add_override
    from services.storage import overrides_table
    from tinydb import Query
    overrides_table.remove(Query().event_id == event_id)
    refresh_schedule_logic()
    return {"status": "deleted"}

# --- Settings API ---
@app.get("/api/settings")
def get_settings():
    settings = storage.get_settings()
    settings['is_home_assistant'] = os.path.exists('/data/options.json')
    return settings

@app.post("/api/settings")
def update_settings(settings: Settings):
    storage.update_settings(settings.model_dump() if hasattr(settings, 'model_dump') else settings.dict())
    refresh_schedule_logic()
    return {"status": "updated"}

@app.delete("/api/cache")
def clear_caches():
    from services.storage import distance_cache_table, polyline_cache_table, cache_table
    distance_cache_table.truncate()
    polyline_cache_table.truncate()
    cache_table.truncate()
    return {"status": "cleared"}

# --- Telemetry API ---
@app.post("/api/telemetry")
def submit_telemetry(event: TelemetryEvent):
    storage.add_telemetry_event(event.model_dump() if hasattr(event, 'model_dump') else event.dict())
    return {"status": "recorded"}

@app.get("/api/telemetry")
def get_telemetry():
    return storage.get_telemetry_events()

@app.post("/api/telemetry/clear")
def clear_telemetry():
    storage.clear_telemetry_events()
    return {"status": "cleared"}

@app.post("/api/telemetry/test_push")
def test_push_notification(driver_id: str = None):
    subs = storage.get_push_subscriptions()
    if not subs:
        return {"error": "No push subscriptions found"}
        
    for sub in subs:
        if not driver_id or sub.get("driver_id") == driver_id:
            send_push(
                sub.get("driver_id"), 
                [sub], 
                "Test Notification", 
                "This is a test push notification from Chauffeur!", 
                "test_leg"
            )
    return {"status": "sent"}


@app.post("/api/calendars/metadata")
def get_calendars_metadata(calendar_ids: list[str]):
    return calendar.get_calendar_metadata(calendar_ids)

# --- Events API ---
from typing import Optional

class EventDetailsUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    attendees: Optional[list[str]] = None
    source_event_ids: list[str]

@app.patch("/api/events")
def update_event_details(payload: EventDetailsUpdate):
    try:
        details = payload.model_dump(exclude_unset=True) if hasattr(payload, 'model_dump') else payload.dict(exclude_unset=True)
        # remove source_event_ids from details
        details.pop('source_event_ids', None)
        calendar.update_event_details(payload.source_event_ids, details)
        refresh_schedule_logic()
        return {"status": "updated"}
    except Exception as e:
        return {"error": str(e)}

# --- Maps API ---
@app.get("/api/places/autocomplete")
def get_places_autocomplete(input: str):
    suggestions = maps.autocomplete_location(input)
    return {"suggestions": suggestions}

# --- Schedule API ---
import hashlib

def hash_events(events_list):
    sorted_events = sorted(events_list, key=lambda e: getattr(e, 'id', ''))
    parts = []
    for e in sorted_events:
        parts.append(f"{getattr(e, 'id', '')}|{getattr(e, 'start', '')}|{getattr(e, 'end', '')}|{getattr(e, 'location', '')}|{getattr(e, 'title', '')}")
    return hashlib.sha256("||".join(parts).encode('utf-8')).hexdigest()

def refresh_schedule_logic(start_date_str=None, end_date_str=None, force_refresh=False):
    settings = storage.get_settings()
    calendar_ids = settings.get("calendar_ids", [])
    

        
    drivers_data = storage.get_all_drivers()
    # Provide default values for existing drivers to pass Pydantic validation
    for d in drivers_data:
        if 'group' not in d: d['group'] = 'primary'
        if 'priority_index' not in d: d['priority_index'] = 1
        if 'calendar_ids' not in d: d['calendar_ids'] = []
        
    drivers = [Driver(**d) for d in drivers_data if not d.get('is_disabled', False)]
    
    driver_calendar_ids = set()
    for d in drivers:
        for cid in d.calendar_ids:
            if cid and cid.strip():
                driver_calendar_ids.add(cid.strip())
                
    passengers_data = storage.get_all_passengers()
    passengers = [Passenger(**p) for p in passengers_data]
    
    passenger_calendar_ids = set()
    for p in passengers:
        for cid in p.calendar_ids:
            if cid and cid.strip():
                passenger_calendar_ids.add(cid.strip())
                
    all_cals_to_fetch = list(set(calendar_ids) | driver_calendar_ids | passenger_calendar_ids)
    
    # If there are no calendars to fetch at all, return an error
    if not all_cals_to_fetch:
        return {"error": "No calendar IDs configured in settings, drivers, or passengers."}
    
    days_to_show = settings.get("days_to_show", 7)
    
    try:
        all_fetched_events = calendar.fetch_upcoming_events(all_cals_to_fetch, days=days_to_show, start_date_str=start_date_str, end_date_str=end_date_str)
    except Exception as e:
        return {"error": f"Failed to fetch events: {str(e)}"}
        
    # Lazy Solving Check
    current_events_hash = hash_events(all_fetched_events)
    if start_date_str and end_date_str and not force_refresh:
        cached_custom = storage.get_custom_schedule(start_date_str, end_date_str)
        if cached_custom and cached_custom.get('events_hash') == current_events_hash:
            return cached_custom['schedule']

        
    events = []
    all_events_for_ui = {} # To avoid duplicates in payload
    import difflib
    
    def fuzzy_has_hashtag(text, target_tag):
        if not target_tag or not text: return False
        words = [w.lower().strip() for w in text.split()]
        target = target_tag.lower().strip()
        for w in words:
            if w.startswith('#'):
                ratio = difflib.SequenceMatcher(None, w, target).ratio()
                if ratio >= 0.8:
                    return True
        return False

    driver_events_map = {d.id: [] for d in drivers}
    driver_events_ids = {d.id: [] for d in drivers}
    
    for e in all_fetched_events:
        all_events_for_ui[e.id] = e
        
        original_calendar_ids = list(e.calendar_ids)
        is_passenger = any(c in calendar_ids for c in e.calendar_ids)
        
        # Also check passenger tags and passenger calendar IDs
        matched_passengers = []
        for p in passengers:
            # Match by passenger's calendar ID
            if any(c in p.calendar_ids for c in original_calendar_ids):
                is_passenger = True
                if p not in matched_passengers:
                    matched_passengers.append(p)
            # Match by hashtags
            elif p.hashtags:
                for tag in p.hashtags:
                    title_match = fuzzy_has_hashtag(e.title, tag)
                    desc_match = fuzzy_has_hashtag(e.description, tag)
                    if title_match or desc_match:
                        is_passenger = True
                        if p not in matched_passengers:
                            matched_passengers.append(p)
                        break
                        
        if matched_passengers:
            # Replace the generic calendar IDs with the actual passenger IDs.
            # This ensures that "Data Calendars" don't falsely trigger overlap conflicts
            # for different passengers.
            e.calendar_ids = [str(p.id) for p in matched_passengers]
                    
        if is_passenger:
            events.append(e)
            
        for d in drivers:
            # Check calendar_ids
            if any(c in d.calendar_ids for c in original_calendar_ids):
                driver_events_map[d.id].append(e)
                driver_events_ids[d.id].append(e.id)
                continue
            
            # Check driver hashtags
            for tag in d.hashtags:
                if fuzzy_has_hashtag(e.title, tag) or fuzzy_has_hashtag(e.description, tag):
                    driver_events_map[d.id].append(e)
                    driver_events_ids[d.id].append(e.id)
                    break
                
    rules_data = storage.get_all_rules()
    priority_rules_data = storage.get_all_priority_rules()
    overrides_data = storage.get_all_overrides()
    
    rules = [Rule(**r) for r in rules_data]
    priority_rules = [PriorityRule(**pr) for pr in priority_rules_data]
    overrides = [ManualOverride(**o) for o in overrides_data]
    
    # Separate events with no location
    no_location_events = []
    events_to_solve = []
    for e in events:
        if not e.location or not e.location.strip():
            no_location_events.append(e.id)
        else:
            events_to_solve.append(e)
            
    old_cache = storage.get_cached_schedule()
    previous_assignments = old_cache.get("assignments", {})
            
    assignments, unassigned, lateness_warnings = matcher.solve_schedule(
        events_to_solve, drivers, rules, priority_rules, overrides=overrides, previous_assignments=previous_assignments, driver_events=driver_events_map, passengers=passengers
    )
    
    # Ghost Routes
    unassigned_events = [e for e in events_to_solve if e.id in unassigned]
    
    # Pass the events that were successfully assigned to real drivers
    assigned_events = [e for e in events_to_solve if e.id in assignments]
    ghost_assignments, ghost_drivers = matcher.solve_ghost_routes(unassigned_events, assigned_events)
    
    # Route Edges
    all_assignments = {**assignments, **ghost_assignments}
    home_location = maps.get_home_location()
    route_edges, initial_edges, final_edges = matcher.compute_route_edges(all_assignments, events_to_solve, drivers, home_location=home_location, driver_attendances=driver_events_ids)
    
    # True Unassigned (dropped due to passenger conflicts)
    true_unassigned = [e.id for e in unassigned_events if e.id not in ghost_assignments]
    
    # Conflicts
    conflicts = matcher.compute_conflicts(assignments, ghost_assignments, events_to_solve)
    
    calendar_metadata = calendar.get_calendar_metadata(all_cals_to_fetch)
    
    PALETTE = [
        "#3B82F6", "#10B981", "#8B5CF6", "#EC4899", 
        "#14B8A6", "#F97316", "#06B6D4", "#84CC16"
    ]
    
    # Inject passenger metadata so the UI renders their badges nicely
    for p in passengers:
        # Fallback to a deterministic color based on their passenger ID
        color_index = sum(ord(c) for c in str(p.id)) % len(PALETTE)
        bg_color = PALETTE[color_index]
        fg_color = "#ffffff"
        
        if p.calendar_ids:
            # Try to grab the color from the passenger's first associated calendar
            primary_cal = p.calendar_ids[0]
            if primary_cal in calendar_metadata:
                bg_color = calendar_metadata[primary_cal].get("backgroundColor", bg_color)
                fg_color = calendar_metadata[primary_cal].get("foregroundColor", fg_color)
                
        calendar_metadata[str(p.id)] = {
            "summary": p.name,
            "backgroundColor": bg_color,
            "foregroundColor": fg_color
        }
    
    overridden_event_ids = [o.event_id for o in overrides]
    
    diagnostics = matcher.compute_diagnostics(
        true_unassigned, events_to_solve, drivers, driver_events_map, assignments, overrides, rules, passengers=passengers
    )
    
    duplicate_groups = []
    mut_ex_keywords = [r.event_keyword.lower() for r in rules if r.constraint_type == 'mutually_exclusive']
    from collections import defaultdict
    dup_groups = defaultdict(list)
    for e in events_to_solve:
        date_str = e.start.strftime('%Y-%m-%d')
        core_title = e.title.split(' - ')[0].split(':')[0].strip()
        core_title_lower = core_title.lower()
        
        if any(kw in core_title_lower for kw in mut_ex_keywords):
            continue
            
        cals_tuple = tuple(sorted(e.calendar_ids))
        duration = (e.end - e.start).total_seconds()
        
        if len(core_title) > 3:
            key = (date_str, core_title, duration, cals_tuple)
            dup_groups[key].append(e)
            
    for key, evs in dup_groups.items():
        if len(evs) > 1:
            duplicate_groups.append({
                "date": key[0],
                "keyword": key[1],
                "original_titles": [e.title for e in evs],
                "event_ids": [e.id for e in evs]
            })

    data = jsonable_encoder({
        "duplicate_groups": duplicate_groups,
        "events": list(all_events_for_ui.values()),
        "assignments": assignments,
        "ghost_assignments": ghost_assignments,
        "ghost_drivers": ghost_drivers,
        "route_edges": route_edges,
        "initial_edges": initial_edges,
        "final_edges": final_edges,
        "conflicts": conflicts,
        "unassigned": true_unassigned,
        "no_location": no_location_events,
        "overridden_events": overridden_event_ids,
        "calendar_metadata": calendar_metadata,
        "lateness_warnings": lateness_warnings,
        "passenger_calendar_ids": calendar_ids,
        "driver_events": driver_events_ids,
        "home_location": home_location or "",
        "diagnostics": diagnostics,
        "passengers": passengers,
        "drivers": drivers
    })
    
    if not start_date_str and not end_date_str:
        storage.set_cached_schedule(data)
    else:
        storage.save_custom_schedule(start_date_str, end_date_str, data, current_events_hash)

    if start_date_str is None and end_date_str is None:
        # --- Generate Pending Notifications ---
        pending_notifications = []
        events_by_id = {e.id: e for e in all_events_for_ui.values()}
        now_ts = datetime.now().timestamp()
        
        # Preserve fired status
        existing_notifs = storage.get_pending_notifications()
        fired_notif_ids = {n["notif_id"] for n in existing_notifs if n.get("fired")}
        
        # Collect all drivers from edges
        all_driver_ids = set()
        all_driver_ids.update(data.get("initial_edges", {}).keys())
        all_driver_ids.update(data.get("route_edges", {}).keys())
        all_driver_ids.update(data.get("final_edges", {}).keys())
        
        for d_id in all_driver_ids:
            if d_id.startswith('ghost_'): continue
            
            for ev_id, edge in data.get("initial_edges", {}).get(d_id, {}).items():
                ev = events_by_id.get(ev_id)
                if not ev: continue
                dep_time = datetime.fromisoformat(ev.start.isoformat()).timestamp() - (edge.get("travel_mins", 0) + 5) * 60
                if now_ts <= dep_time + 600:
                    notif_id = f"init_{ev_id}"
                    pending_notifications.append({
                        "notif_id": notif_id,
                        "driver_id": d_id,
                        "trigger_timestamp": dep_time,
                        "title": "Time to Leave!",
                        "body": f"Drive to {ev.location.split(',')[0]}",
                        "location": ev.location,
                        "fired": notif_id in fired_notif_ids
                    })
                    
            for ev_id, edge in data.get("route_edges", {}).get(d_id, {}).items():
                ev = events_by_id.get(ev_id)
                next_ev = events_by_id.get(edge.get("to_event", ""))
                if not ev or not next_ev: continue
                dep_time = datetime.fromisoformat(ev.end.isoformat()).timestamp()
                if now_ts <= dep_time + 600:
                    notif_id = f"route_{ev_id}_{next_ev.id}"
                    pending_notifications.append({
                        "notif_id": notif_id,
                        "driver_id": d_id,
                        "trigger_timestamp": dep_time,
                        "title": "Time to Leave!",
                        "body": f"Drive to {next_ev.location.split(',')[0]}",
                        "location": next_ev.location,
                        "fired": notif_id in fired_notif_ids
                    })
                    
            for ev_id, edge in data.get("final_edges", {}).get(d_id, {}).items():
                ev = events_by_id.get(ev_id)
                if not ev: continue
                dep_time = datetime.fromisoformat(ev.end.isoformat()).timestamp()
                if now_ts <= dep_time + 600:
                    notif_id = f"final_{ev_id}"
                    pending_notifications.append({
                        "notif_id": notif_id,
                        "driver_id": d_id,
                        "trigger_timestamp": dep_time,
                        "title": "Time to Leave!",
                        "body": "Drive Home",
                        "location": settings.get("home_location", ""),
                        "fired": notif_id in fired_notif_ids
                    })
                    
        storage.save_pending_notifications(pending_notifications)
        # ----------------------------------------
    
    return data


from fastapi.responses import FileResponse
@app.get("/sw.js")
def get_service_worker():
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"), media_type="application/javascript")

@app.get("/api/vapid_public_key")
def get_vapid_public_key():
    # Return the URL-safe base64 VAPID public key
    return {"public_key": VAPID_PUBLIC_KEY_STR}

@app.post("/api/push_subscribe")
def push_subscribe(sub: PushSubscription):
    storage.save_push_subscription(sub.driver_id, sub.subscription)
    return {"status": "ok"}

@app.post("/api/drive_status")
def update_drive_status(status: DriveStatus):
    storage.mark_drive_status(status.leg_id, status.status)
    return {"status": "ok"}

custom_schedule_cache = {}

from fastapi import BackgroundTasks

@app.get("/api/schedule")
def get_schedule(background_tasks: BackgroundTasks, start_date: str = None, end_date: str = None, force_refresh: bool = False):
    try:
        completed = storage.get_completed_drives()
        
        # Check cache instantly
        if not force_refresh:
            if not start_date and not end_date:
                cached = storage.get_cached_schedule()
            else:
                cached_custom = storage.get_custom_schedule(start_date, end_date)
                cached = cached_custom.get('schedule') if cached_custom else None
                
            if cached:
                cached["completed_drives"] = completed
                # Fire an async background refresh so Google Calendar latency (1-5s) doesn't block the UI
                background_tasks.add_task(refresh_schedule_logic, start_date, end_date, False)
                return cached

        # Fetch fresh and block if no cache exists or forced
        try:
            res = refresh_schedule_logic(start_date, end_date, force_refresh=force_refresh)
            if "error" not in res:
                res["completed_drives"] = completed
            return res
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc(), "error_debug": str(e)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/ha_sensors")
def get_ha_sensors():
    try:
        cache = storage.get_cached_schedule()
        if not cache:
            cache = refresh_schedule_logic()
            
        import urllib.parse
        from datetime import datetime
        
        # 1. Unassigned Events
        unassigned_ids = cache.get("unassigned", [])
        no_loc_ids = cache.get("no_location", [])
        all_unassigned_ids = list(set(unassigned_ids + no_loc_ids))
        
        events_map = {e["id"]: e for e in cache.get("events", [])}
        unassigned_events = [events_map[eid] for eid in all_unassigned_ids if eid in events_map]
        
        # 2. Suggested Routes (Ghost Drivers)
        ghost_drivers = cache.get("ghost_drivers", [])
        ghost_assignments = cache.get("ghost_assignments", {})
        
        suggested_routes = []
        for g in ghost_drivers:
            g_events = [events_map[eid] for eid, gid in ghost_assignments.items() if gid == g["id"] and eid in events_map]
            g_events.sort(key=lambda x: x["start"])
            suggested_routes.append({
                "route_name": g["name"],
                "events": g_events
            })
            
        # 3. Schedule By Date (Maps Links)
        assignments = cache.get("assignments", {})
        drivers_data = storage.get_all_drivers()
        driver_events_map = cache.get("driver_events", {})
        
        # Collect all unique dates across all drivers
        all_unique_events = []
        for d in drivers_data:
            if d.get("is_disabled"): continue
            d_id = d["id"]
            assigned_evs = [events_map[eid] for eid, did in assignments.items() if did == d_id and eid in events_map]
            personal_evs = [events_map[eid] for eid in driver_events_map.get(d_id, []) if eid in events_map]
            all_unique_events.extend(assigned_evs + personal_evs)
            
        unique_dates = set(datetime.fromisoformat(e["start"].replace('Z', '+00:00')).date() for e in all_unique_events)
        sorted_dates = sorted(list(unique_dates))
        
        schedule_by_date = []
        for target_date in sorted_dates:
            driver_routes = []
            for d in drivers_data:
                if d.get("is_disabled"): continue
                
                d_id = d["id"]
                # Events assigned to this driver
                assigned_evs = [events_map[eid] for eid, did in assignments.items() if did == d_id and eid in events_map]
                # Events where the driver is a passenger
                personal_evs = [events_map[eid] for eid in driver_events_map.get(d_id, []) if eid in events_map]
                
                all_d_events = assigned_evs + personal_evs
                # Filter distinct by id
                unique_d_events = {e["id"]: e for e in all_d_events}.values()
                
                # Filter for target_date
                daily_events = [e for e in unique_d_events if datetime.fromisoformat(e["start"].replace('Z', '+00:00')).date() == target_date]
                daily_events.sort(key=lambda x: x["start"])
                
                if len(daily_events) == 0:
                    continue
                
                route_edges = cache.get("route_edges", {})
                home_loc = maps.get_home_location()
                
                # Generate Individual Event Data
                enriched_events = []
                for i, ev in enumerate(daily_events):
                    ev_copy = ev.copy()
                    
                    # Calculate Departure Time
                    departure_time = None
                    suggested_notification_time = None
                    
                    ev_start = datetime.fromisoformat(ev["start"].replace('Z', '+00:00'))
                    
                    if i == 0:
                        # First event of the day
                        travel_mins = maps.get_travel_time_minutes(home_loc, ev.get("location"))
                        departure_time = ev_start - timedelta(minutes=travel_mins)
                        suggested_notification_time = departure_time - timedelta(minutes=30)
                    else:
                        prev_ev = daily_events[i-1]
                        edge = route_edges.get(prev_ev["id"], {})
                        if edge.get("home_waypoint"):
                            travel_mins = edge["home_waypoint"].get("from_home_mins", 0)
                            departure_time = ev_start - timedelta(minutes=travel_mins)
                            suggested_notification_time = departure_time - timedelta(minutes=30)
                        else:
                            travel_mins = edge.get("travel_mins", 0)
                            departure_time = ev_start - timedelta(minutes=travel_mins)
                            suggested_notification_time = departure_time - timedelta(minutes=5)
                            
                    ev_copy["departure_time"] = departure_time.isoformat() if departure_time else None
                    ev_copy["suggested_notification_time"] = suggested_notification_time.isoformat() if suggested_notification_time else None
                    ev_copy["travel_mins"] = travel_mins
                    
                    if travel_mins >= 60:
                        ev_copy["travel_time_formatted"] = f"{travel_mins // 60}h {travel_mins % 60}m"
                    else:
                        ev_copy["travel_time_formatted"] = f"{travel_mins}m"
                    
                    # Maps URL for single event
                    if ev.get("location"):
                        if d.get("preferred_maps_provider") == "apple":
                            ev_copy["map_url"] = maps.get_apple_maps_url([ev["location"]])
                        else:
                            ev_copy["map_url"] = maps.get_google_maps_url([ev["location"]])
                    else:
                        ev_copy["map_url"] = ""
                    enriched_events.append(ev_copy)
                
                # Generate Multi-stop Maps Link
                locations = [e["location"] for e in daily_events if e.get("location")]
                if d.get("preferred_maps_provider") == "apple":
                    maps_url = maps.get_apple_maps_url(locations)
                else:
                    maps_url = maps.get_google_maps_url(locations)
                # Generate Notification Email Address
                notification_email_address = None
                if d.get("phone_number") and d.get("cell_carrier"):
                    import re
                    phone = re.sub(r'\D', '', str(d["phone_number"]))
                    carrier = d["cell_carrier"].lower()
                    domains = {
                        "att": "txt.att.net",
                        "verizon": "vtext.com",
                        "tmobile": "tmomail.net",
                        "sprint": "messaging.sprintpcs.com",
                        "googlefi": "msg.fi.google.com"
                    }
                    if carrier in domains and len(phone) >= 10:
                        # use last 10 digits
                        notification_email_address = f"{phone[-10:]}@{domains[carrier]}"
                        
                driver_routes.append({
                    "driver_name": d["name"],
                    "event_count": len(daily_events),
                    "maps_url": maps_url,
                    "notification_email_address": notification_email_address,
                    "events": enriched_events
                })
                
            if driver_routes:
                schedule_by_date.append({
                    "date": str(target_date),
                    "driver_routes": driver_routes
                })

        return {
            "unassigned_count": len(all_unassigned_ids),
            "unassigned_events": unassigned_events,
            "suggested_routes_count": len(ghost_drivers),
            "suggested_routes": suggested_routes,
            "schedule_by_date": schedule_by_date
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.post("/api/schedule/refresh")
def force_refresh_schedule():
    return refresh_schedule_logic()

@app.get("/api/maps/test_polyline")
def test_polyline(origin: str, destination: str):
    import requests
    api_key = maps.get_api_key()
    if not api_key:
        return {"error": "No API key"}
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.polyline.encodedPolyline"
    }
    payload = {
        "origin": {
            "address": origin
        },
        "destination": {
            "address": destination
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": "true",
        "routeModifiers": {
            "avoidTolls": "true",
            "avoidHighways": "false",
            "avoidFerries": "true"
        }
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/maps/route_info")
def get_route_info(origin: str, destination: str):
    info = maps.get_route_info(origin, destination)
    if not info:
        return {"error": "No route found"}
    return info

@app.get("/api/maps/static")
def get_static_map(location: str, origin: str = None, theme: str = "dark"):
    """Proxy Google Static Maps API to keep the API key server-side."""
    import requests
    api_key = maps.get_api_key()
    if not api_key:
        return Response(content="No API key configured", status_code=503)

    params = [
        ("size", "600x300"),
        ("scale", "2"),
        ("maptype", "roadmap"),
        ("key", api_key),
        ("markers", f"color:red|{location}")
    ]

    if theme == "dark":
        params.extend([
            ("style", "feature:all|element:geometry|color:0x242f3e"),
            ("style", "feature:all|element:labels.text.fill|color:0x746855"),
            ("style", "feature:all|element:labels.text.stroke|color:0x242f3e"),
            ("style", "feature:water|element:geometry|color:0x17263c"),
            ("style", "feature:road|element:geometry|color:0x38414e"),
            ("style", "feature:road|element:geometry.stroke|color:0x212a37"),
            ("style", "feature:poi|element:geometry|color:0x283d6a"),
        ])

    if origin:
        info = maps.get_route_info(origin, location)
        polyline = info.get("polyline") if info else None
        if polyline:
            params.append(("path", f"color:0x4A90D9|weight:4|enc:{polyline}"))
        else:
            params.append(("path", f"color:0x4A90D9|weight:4|{origin}|{location}"))
            
        # Replace the single marker with origin + destination markers
        params = [(k, v) for k, v in params if k != "markers"]
        params.append(("markers", f"color:green|label:A|{origin}"))
        params.append(("markers", f"color:red|label:B|{location}"))

    try:
        import urllib.parse
        query_parts = []
        for k, v in params:
            if k == "path" and "enc:" in v:
                query_parts.append(f"{k}={v}")
            else:
                query_parts.append(f"{k}={urllib.parse.quote(str(v), safe=':|')}")
        
        url = "https://maps.googleapis.com/maps/api/staticmap?" + "&".join(query_parts)
        import urllib.request
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
            status_code = resp.getcode()
            content_type = resp.headers.get("Content-Type", "")
            
        if status_code == 200 and content_type.startswith("image"):
            return Response(content=content, media_type="image/png")
        print(f"Static Maps API error: status={status_code}, body={content[:500]}")
        return Response(content="Map unavailable", status_code=status_code)
    except Exception as ex:
        print(f"Static Maps API error: {ex}")
        return Response(content="Map unavailable", status_code=500)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
