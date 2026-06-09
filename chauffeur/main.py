from fastapi import FastAPI, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from models.schemas import Driver, Rule, Settings, PriorityRule, ManualOverride
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_schedule())
    yield
    task.cancel()

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
def refresh_schedule_logic():
    settings = storage.get_settings()
    calendar_ids = settings.get("calendar_ids", [])
    
    if not calendar_ids:
        return {"error": "No calendar IDs configured in settings."}
        
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
                
    all_cals_to_fetch = list(set(calendar_ids) | driver_calendar_ids)
    
    days_to_show = settings.get("days_to_show", 7)
    
    try:
        all_fetched_events = calendar.fetch_upcoming_events(all_cals_to_fetch, days=days_to_show)
    except Exception as e:
        return {"error": f"Failed to fetch events: {str(e)}"}
        
    events = []
    all_events_for_ui = {} # To avoid duplicates in payload
    driver_events_map = {d.id: [] for d in drivers}
    driver_events_ids = {d.id: [] for d in drivers}
    
    for e in all_fetched_events:
        all_events_for_ui[e.id] = e
        
        is_passenger = any(c in calendar_ids for c in e.calendar_ids)
        if is_passenger:
            events.append(e)
            
        for d in drivers:
            if any(c in d.calendar_ids for c in e.calendar_ids):
                driver_events_map[d.id].append(e)
                driver_events_ids[d.id].append(e.id)
                
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
        events_to_solve, drivers, rules, priority_rules, overrides=overrides, previous_assignments=previous_assignments, driver_events=driver_events_map
    )
    
    # Ghost Routes
    unassigned_events = [e for e in events_to_solve if e.id in unassigned]
    
    # Pass the events that were successfully assigned to real drivers
    assigned_events = [e for e in events_to_solve if e.id in assignments]
    ghost_assignments, ghost_drivers = matcher.solve_ghost_routes(unassigned_events, assigned_events)
    
    # Route Edges
    all_assignments = {**assignments, **ghost_assignments}
    home_location = maps.get_home_location()
    route_edges, initial_edges = matcher.compute_route_edges(all_assignments, events_to_solve, home_location=home_location)
    
    # True Unassigned (dropped due to passenger conflicts)
    true_unassigned = [e.id for e in unassigned_events if e.id not in ghost_assignments]
    
    # Conflicts
    conflicts = matcher.compute_conflicts(assignments, ghost_assignments, events_to_solve)
    
    calendar_metadata = calendar.get_calendar_metadata(all_cals_to_fetch)
    
    overridden_event_ids = [o.event_id for o in overrides]
    
    data = jsonable_encoder({
        "events": list(all_events_for_ui.values()),
        "assignments": assignments,
        "ghost_assignments": ghost_assignments,
        "ghost_drivers": ghost_drivers,
        "route_edges": route_edges,
        "initial_edges": initial_edges,
        "conflicts": conflicts,
        "unassigned": true_unassigned,
        "no_location": no_location_events,
        "overridden_events": overridden_event_ids,
        "calendar_metadata": calendar_metadata,
        "lateness_warnings": lateness_warnings,
        "passenger_calendar_ids": calendar_ids,
        "driver_events": driver_events_ids,
        "home_location": home_location or ""
    })
    
    storage.set_cached_schedule(data)
    return data

@app.get("/api/schedule")
def get_schedule():
    try:
        cache = storage.get_cached_schedule()
        if cache:
            return cache
        # First time run
        return refresh_schedule_logic()
    except Exception as e:
        import traceback
        return {"error_debug": str(e), "traceback": traceback.format_exc()}

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
