from fastapi import FastAPI, BackgroundTasks
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
    route_edges = matcher.compute_route_edges(all_assignments, events_to_solve)
    
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
        "conflicts": conflicts,
        "unassigned": true_unassigned,
        "no_location": no_location_events,
        "overridden_events": overridden_event_ids,
        "calendar_metadata": calendar_metadata,
        "lateness_warnings": lateness_warnings,
        "passenger_calendar_ids": calendar_ids,
        "driver_events": driver_events_ids
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

@app.post("/api/schedule/refresh")
def force_refresh_schedule():
    return refresh_schedule_logic()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
