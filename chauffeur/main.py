import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from fastapi import FastAPI, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse, HTMLResponse
import asyncio
import time

LAST_UPDATE_TIME = time.time()

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

from models.schemas import Driver, Rule, Settings, PriorityRule, ManualOverride, Passenger, TelemetryEvent, Errand, ErrandRule
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
            await asyncio.to_thread(trigger_background_refresh)
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
    return RedirectResponse(url="dashboard_v2")

@app.get("/dashboard")
def dashboard_legacy():
    return RedirectResponse(url="dashboard_v2")

@app.get("/dashboard_v2")
def dashboard(request: Request):
    response = templates.TemplateResponse(request=request, name="dashboard.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/app")
def driver_app(request: Request):
    return templates.TemplateResponse(request=request, name="app.html")

@app.get("/config")
def config(request: Request):
    return templates.TemplateResponse(request=request, name="config.html")

@app.get("/calendar", response_class=HTMLResponse)
def calendar_view(request: Request):
    return templates.TemplateResponse(request=request, name="calendar.html")

@app.get("/errands")
def errands(request: Request):
    return templates.TemplateResponse(request=request, name="errands.html")

@app.get("/trips")
def trips_list_view(request: Request):
    response = templates.TemplateResponse(request=request, name="trips.html", context={})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/api/trips")
def get_all_trips_api():
    settings = storage.get_settings()
    calendar_ids = settings.get('calendar_ids', [])
    trip_hashtags = settings.get('trip_hashtags', [])
    
    from datetime import datetime as dt, timedelta, timezone
    now = dt.now()
    time_min = (now - timedelta(days=30)).isoformat() + 'Z'
    time_max = (now + timedelta(days=365)).isoformat() + 'Z'
    
    from services.calendar import get_calendar_service
    try:
        service = get_calendar_service()
    except Exception as e:
        return {"error": str(e), "trips": []}
        
    trips_map = {}
    
    def parse_dt_iso(s):
        if len(s) <= 10:
            return dt.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
        return dt.fromisoformat(s.replace('Z', '+00:00')).isoformat()
        
    def add_trip(cal_id, g):
        if g.get('status') == 'cancelled': return
        start_str = g.get('start', {}).get('dateTime', g.get('start', {}).get('date'))
        end_str = g.get('end', {}).get('dateTime', g.get('end', {}).get('date'))
        if not start_str or not end_str: return
        
        event_id = f"{cal_id}::{g['id']}"
        if event_id in trips_map: return
        
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            base_id = f"{cal_id}::{g['id'].split('_')[0]}"
            meta = storage.get_trip_metadata(base_id)
        meta = meta or {}
            
        trips_map[event_id] = {
            'id': event_id,
            'title': g.get('summary', ''),
            'start': parse_dt_iso(start_str),
            'end': parse_dt_iso(end_str),
            'location': g.get('location', ''),
            'background_url': meta.get('background_url', ''),
            'poi_count': len(meta.get('pois', []))
        }

    # 1. Fetch by Hashtags using Google API Search
    for cal_id in calendar_ids:
        for tag in trip_hashtags:
            try:
                res = service.events().list(
                    calendarId=cal_id, q=tag, singleEvents=True,
                    timeMin=time_min, timeMax=time_max, maxResults=50
                ).execute()
                for g in res.get('items', []):
                    add_trip(cal_id, g)
            except Exception as e:
                print(f"Error searching calendar {cal_id} for tag {tag}: {e}")

    # 2. Fetch by explicit DB setting
    from services.storage import event_configs_table, trip_metadata_table
    trip_event_ids = set()
    with storage.db_lock:
        all_activities = set()
        for doc in event_configs_table.all():
            if doc.get('is_trip'):
                trip_event_ids.add(doc.get('google_id'))
            if doc.get('trip_id'):
                gid = doc.get('google_id')
                trip_cal_id = doc.get('trip_id').split("::", 1)[0] if "::" in doc.get('trip_id') else "primary"
                full_gid = gid if "::" in gid else f"{trip_cal_id}::{gid}"
                all_activities.add(full_gid)
                
        for doc in trip_metadata_table.all():
            all_activities.update(doc.get('activities', []))
            
        for doc in trip_metadata_table.all():
            if doc.get('is_draft'):
                from datetime import datetime, timezone
                trips_map[doc['event_id']] = {
                    'id': doc['event_id'],
                    'title': doc.get('title', 'Draft Trip'),
                    'start': datetime.fromtimestamp(doc['mock_start_date'], tz=timezone.utc).isoformat() if doc.get('mock_start_date') else '',
                    'end': datetime.fromtimestamp(doc['mock_end_date'], tz=timezone.utc).isoformat() if doc.get('mock_end_date') else '',
                    'location': doc.get('location', ''),
                    'background_url': doc.get('background_url', ''),
                    'poi_count': len(doc.get('pois', [])),
                    'is_draft': True
                }
                continue
            if not doc.get('is_activity') and doc.get('event_id') not in all_activities:
                trip_event_ids.add(doc.get('event_id'))
            
    for event_id in trip_event_ids:
        if "::" not in event_id or event_id in trips_map:
            continue
        cal_id, raw_event_id = event_id.split("::", 1)
        try:
            g = service.events().get(calendarId=cal_id, eventId=raw_event_id).execute()
            add_trip(cal_id, g)
        except Exception as e:
            print(f"Error fetching trip {event_id}: {e}")

    trips_list = list(trips_map.values())
    trips_list.sort(key=lambda x: x['start'] if x['start'] else '')
    return {"trips": trips_list}

from models.schemas import CreateTripRequest

@app.post("/api/trips")
def create_trip_api(req: CreateTripRequest):
    settings = storage.get_settings()
    
    if not req.start_date or not req.end_date:
        import uuid
        from datetime import datetime, timedelta
        
        draft_id = f"draft_trip_{uuid.uuid4().hex}"
        
        # Calculate a mock date in 2030 aligning with req.start_day_of_week
        # Jan 1, 2030 is a Tuesday (weekday 1)
        base = datetime(2030, 1, 1)
        day_of_week = req.start_day_of_week if req.start_day_of_week is not None else 0 # default Monday
        offset = (day_of_week - base.weekday()) % 7
        if offset < 0:
            offset += 7
        mock_start = base + timedelta(days=offset, hours=9) # Start at 9 AM
        duration = req.duration_days or 1
        mock_end = mock_start + timedelta(days=duration)
        
        metadata = {
            "event_id": draft_id,
            "is_draft": True,
            "title": req.title,
            "location": req.location,
            "draft_start_day": req.start_day_of_week,
            "draft_duration_days": req.duration_days,
            "mock_start_date": mock_start.timestamp(),
            "mock_end_date": mock_end.timestamp(),
            "pois": [],
            "activities": []
        }
        storage.set_trip_metadata(draft_id, metadata)
        return {"success": True, "event_id": draft_id}

    cal_id = req.calendar_id or (settings.get('calendar_ids', [])[0] if settings.get('calendar_ids') else "primary")
    
    event_body = {
        "summary": req.title,
        "description": "#trip",
        "start": {"date": req.start_date} if len(req.start_date) == 10 else {"dateTime": req.start_date},
        "end": {"date": req.end_date} if len(req.end_date) == 10 else {"dateTime": req.end_date},
    }
    if req.location:
        event_body["location"] = req.location

    try:
        service = calendar.get_calendar_service()
        created = service.events().insert(calendarId=cal_id, body=event_body).execute()
        event_id = f"{cal_id}::{created['id']}"
        
        # Initialize empty metadata so it appears as a trip immediately
        metadata = storage.get_trip_metadata(event_id)
        if not metadata:
            metadata = {"event_id": event_id, "pois": [], "activities": []}
            storage.set_trip_metadata(event_id, metadata)
            
        return {"success": True, "event_id": event_id}
    except Exception as e:
        return {"error": str(e)}

@app.get("/trip")
def trip_view(request: Request, event_id: str):
    response = templates.TemplateResponse(request=request, name="trip.html", context={"event_id": event_id})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/api/trip/{event_id}")
def get_trip_api(event_id: str):
    metadata = storage.get_trip_metadata(event_id)
    
    if event_id.startswith("draft_trip_"):
        if not metadata:
            return {"error": "Draft trip not found"}
        from datetime import datetime, timezone
        mock_start = metadata.get("mock_start_date")
        mock_end = metadata.get("mock_end_date")
        
        tz_str = metadata.get("timeZone")
        if (not tz_str or tz_str == "UTC") and metadata.get("location"):
            from services.maps import get_timezone
            new_tz = get_timezone(metadata.get("location"))
            if new_tz and new_tz != "UTC":
                tz_str = new_tz
                metadata["timeZone"] = tz_str
                storage.set_trip_metadata(event_id, metadata)
            
        event_details = {
            "id": event_id,
            "title": metadata.get("title", "Draft Trip"),
            "location": metadata.get("location", ""),
            "start": mock_start if mock_start else datetime.now(timezone.utc).timestamp(),
            "end": mock_end if mock_end else datetime.now(timezone.utc).timestamp(),
            "timeZone": tz_str or "UTC"
        }
        
        activities_details = []
        for poi in metadata.get("pois", []):
            if poi.get("is_scheduled") and poi.get("event_id"):
                background_url = poi.get("image_url")
                if not background_url:
                    import urllib.parse
                    query = poi.get("name") or poi.get("location", "travel")
                    encoded_query = urllib.parse.quote(query)
                    background_url = f"/api/unsplash/background?query={encoded_query}"
                    
                activities_details.append({
                    "id": poi.get("event_id"),
                    "title": poi.get("name", ""),
                    "location": poi.get("location", ""),
                    "description": poi.get("description", ""),
                    "start": poi.get("scheduled_start", 0),
                    "end": poi.get("scheduled_end", 0),
                    "background_url": background_url
                })
        activities_details.sort(key=lambda x: x["start"] if x["start"] else 0)
        
        return {
            "metadata": metadata,
            "event": event_details,
            "activities": activities_details
        }
    if not metadata and "::" in event_id:
        cal_id, raw_event_id = event_id.split("::", 1)
        base_id = f"{cal_id}::{raw_event_id.split('_')[0]}"
        metadata = storage.get_trip_metadata(base_id)
    metadata = metadata or {"event_id": event_id, "pois": [], "activities": []}
    if "activities" not in metadata:
        metadata["activities"] = []
    
    event_details = None
    service = None
    if "::" in event_id:
        cal_id, raw_event_id = event_id.split("::", 1)
        from services.calendar import get_calendar_service
        try:
            service = get_calendar_service()
            g = service.events().get(calendarId=cal_id, eventId=raw_event_id).execute()
            
            start_str = g['start'].get('dateTime', g['start'].get('date'))
            end_str = g['end'].get('dateTime', g['end'].get('date'))
            
            from datetime import datetime, timezone
            def parse_dt(s):
                if not s: return 0
                if len(s) <= 10:
                    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
                return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
                
            event_details = {
                "id": event_id,
                "title": g.get("summary", ""),
                "location": g.get("location", ""),
                "start": parse_dt(start_str),
                "end": parse_dt(end_str),
                "timeZone": g['start'].get('timeZone', g.get('timeZone', 'UTC'))
            }
        except Exception as e:
            print(f"Error fetching trip details from Google Calendar: {e}")
            
    # Merge activities from event configs that have this trip_id
    from services.storage import event_configs_table
    from tinydb import Query
    linked_configs = event_configs_table.search(Query().trip_id == event_id)
    trip_cal_id = event_id.split("::", 1)[0] if "::" in event_id else "primary"
    
    for conf in linked_configs:
        gid = conf.get('google_id')
        if gid:
            full_gid = gid if "::" in gid else f"{trip_cal_id}::{gid}"
            if full_gid not in metadata["activities"]:
                metadata["activities"].append(full_gid)
            
    # Resolve activities
    activities_details = []
    for act_id in metadata["activities"]:
        if "::" not in act_id: continue
        act_cal_id, act_raw_id = act_id.split("::", 1)
        try:
            if service:
                g_act = service.events().get(calendarId=act_cal_id, eventId=act_raw_id).execute()
                act_start_str = g_act.get('start', {}).get('dateTime', g_act.get('start', {}).get('date'))
                act_end_str = g_act.get('end', {}).get('dateTime', g_act.get('end', {}).get('date'))
                
                # Cache Unsplash Background
                act_meta = storage.get_trip_metadata(act_id) or {"event_id": act_id, "is_activity": True}
                if "background_url" not in act_meta or not act_meta.get("is_activity"):
                    act_meta["is_activity"] = True
                    import urllib.parse
                    query = g_act.get("location") or g_act.get("summary", "travel")
                    encoded_query = urllib.parse.quote(query)
                    act_meta["background_url"] = act_meta.get("background_url", f"https://loremflickr.com/1280/720/{encoded_query},scenery")
                    storage.set_trip_metadata(act_id, act_meta)
                    
                activities_details.append({
                    "id": act_id,
                    "title": g_act.get("summary", ""),
                    "location": g_act.get("location", ""),
                    "description": g_act.get("description", ""),
                    "start": parse_dt(act_start_str),
                    "end": parse_dt(act_end_str),
                    "background_url": act_meta.get("background_url")
                })
        except Exception as e:
            print(f"Error fetching activity {act_id}: {e}")
            
    # Sort activities by start time
    activities_details.sort(key=lambda x: x["start"] if x["start"] else 0)
            
    return {
        "event": event_details,
        "metadata": metadata,
        "activities": activities_details
    }

@app.post("/api/trip/{event_id}/activity")
def add_activity_api(event_id: str, payload: dict):
    # payload can contain {"activity_id": "cal::event"} to link existing
    # or {"title": "...", "location": "...", "start": "...", "end": "...", "calendar_id": "..."} to create new
    meta = storage.get_trip_metadata(event_id) or {"event_id": event_id, "pois": [], "activities": []}
    if "activities" not in meta:
        meta["activities"] = []
        
    act_id = payload.get("activity_id")
    if not act_id and "title" in payload:
        # Create new event
        from services.calendar import get_calendar_service
        service = get_calendar_service()
        cal_id = payload.get("calendar_id", "primary")
        event_body = {
            "summary": payload["title"],
            "location": payload.get("location", ""),
            "start": {"dateTime": payload["start"]},
            "end": {"dateTime": payload["end"]}
        }
        res = service.events().insert(calendarId=cal_id, body=event_body).execute()
        act_id = f"{cal_id}::{res['id']}"
        
    if act_id and act_id not in meta["activities"]:
        meta["activities"].append(act_id)
        storage.set_trip_metadata(event_id, meta)
        
    return {"status": "ok", "activity_id": act_id}

@app.delete("/api/trip/{event_id}/activity/{activity_id}")
def delete_activity_api(event_id: str, activity_id: str, delete_from_calendar: bool = False):
    meta = storage.get_trip_metadata(event_id)
    if meta:
        changed = False
        if "activities" in meta and activity_id in meta["activities"]:
            meta["activities"].remove(activity_id)
            changed = True
            
        for poi in meta.get("pois", []):
            if poi.get("event_id") == activity_id:
                poi["is_scheduled"] = False
                poi["event_id"] = None
                poi["scheduled_start"] = None
                poi["scheduled_end"] = None
                changed = True
                break
                
        if changed:
            storage.set_trip_metadata(event_id, meta)
    if delete_from_calendar and "::" in activity_id:
        cal_id, raw_id = activity_id.split("::", 1)
        try:
            from services.calendar import get_calendar_service
            service = get_calendar_service()
            service.events().delete(calendarId=cal_id, eventId=raw_id).execute()
        except Exception as e:
            print(f"Error deleting activity from calendar: {e}")
            
    return {"status": "ok"}

@app.delete("/api/trip/{event_id}/activities")
def clear_itinerary_api(event_id: str, delete_from_calendar: bool = False):
    meta = storage.get_trip_metadata(event_id)
    if not meta: return {"status": "ok"}
    
    activities_to_delete = meta.get("activities", [])
    
    changed = False
    if "activities" in meta and meta["activities"]:
        meta["activities"] = []
        changed = True
        
    for poi in meta.get("pois", []):
        if poi.get("is_scheduled") or poi.get("event_id"):
            poi["is_scheduled"] = False
            poi["event_id"] = None
            poi["scheduled_start"] = None
            poi["scheduled_end"] = None
            changed = True
            
    if changed:
        storage.set_trip_metadata(event_id, meta)
        
    if delete_from_calendar:
        try:
            from services.calendar import get_calendar_service
            service = get_calendar_service()
            for act_id in activities_to_delete:
                if "::" in act_id:
                    cal_id, raw_id = act_id.split("::", 1)
                    try:
                        service.events().delete(calendarId=cal_id, eventId=raw_id).execute()
                    except Exception as e:
                        print(f"Error deleting {act_id} from calendar: {e}")
        except Exception as e:
            print(f"Error getting calendar service: {e}")
            
    return {"status": "ok"}

@app.post("/api/trip/{event_id}")
def save_trip_api(event_id: str, payload: dict):
    if payload.get("is_draft"):
        from datetime import datetime, timedelta
        base = datetime(2030, 1, 1) # Tuesday
        day_of_week = payload.get("draft_start_day", 0)
        offset = (day_of_week - base.weekday()) % 7
        if offset < 0:
            offset += 7
        mock_start = base + timedelta(days=offset, hours=9)
        duration = payload.get("draft_duration_days", 1)
        mock_end = mock_start + timedelta(days=duration)
        
        payload["mock_start_date"] = mock_start.timestamp()
        payload["mock_end_date"] = mock_end.timestamp()

    storage.set_trip_metadata(event_id, payload)
    return {"status": "ok"}

@app.delete("/api/trip/{event_id}")
def delete_trip(event_id: str):
    from services import storage
    metadata = storage.get_trip_metadata(event_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Trip not found")
        
    storage.delete_trip_metadata(event_id)
    return {"success": True}

@app.post("/api/trip/{event_id}/generate_pois")
def generate_pois_api(event_id: str, payload: dict):
    user_prompt = payload.get("prompt", "")
    duration_days = payload.get("duration_days", 1)
    
    if not user_prompt:
        return {"error": "Prompt is required"}
        
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"error": "Trip not found"}
        
    from models.schemas import TripMetadata
    trip_obj = TripMetadata(**meta)
    
    from services.trip_planner import generate_trip_pois
    pois = generate_trip_pois(trip_obj, user_prompt, duration_days)
    
    # Save back to trip metadata
    if 'pois' not in meta:
        meta['pois'] = []
    
    for poi in pois:
        poi_dict = poi.model_dump() if hasattr(poi, 'model_dump') else poi.dict()
        meta['pois'].append(poi_dict)
        
    storage.set_trip_metadata(event_id, meta)
    
    return {"pois": meta['pois']}

@app.post("/api/trip/{event_id}/schedule_poi")
def schedule_poi_api(event_id: str, payload: dict):
    try:
        poi_id = payload.get("poi_id")
        if not poi_id:
            return {"error": "poi_id is required"}
            
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
            
        from models.schemas import TripMetadata
        trip_obj = TripMetadata(**meta)
        
        poi = next((p for p in trip_obj.pois if p.id == poi_id), None)
        if not poi:
            return {"error": "POI not found"}
            
        from services.trip_planner import schedule_poi
        event_calendar_id = schedule_poi(trip_obj, poi)
        if not event_calendar_id:
            return {"error": "Failed to schedule POI (no available time slot or calendar missing)"}
            
        # Update POI in DB
        meta['pois'] = [p.model_dump() if hasattr(p, 'model_dump') else p.dict() for p in trip_obj.pois]
        storage.set_trip_metadata(event_id, meta)
        
        return {"status": "ok", "event_id": event_calendar_id}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.post("/api/trip/{event_id}/schedule_pois_bulk")
def schedule_pois_bulk_api(event_id: str, payload: dict):
    try:
        poi_ids = payload.get("poi_ids")
        if not poi_ids or not isinstance(poi_ids, list):
            return {"error": "poi_ids list is required"}
            
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
            
        from models.schemas import TripMetadata
        trip_obj = TripMetadata(**meta)
        
        from services.trip_planner import schedule_pois_bulk
        result = schedule_pois_bulk(trip_obj, poi_ids)
        if not result:
            return {"error": "Failed to schedule some or all POIs."}
            
        # Update POI in DB
        meta['pois'] = [p.model_dump() if hasattr(p, 'model_dump') else p.dict() for p in trip_obj.pois]
        storage.set_trip_metadata(event_id, meta)
        
        return {"status": "ok", "scheduled_count": len(poi_ids)}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


# --- Drivers API ---
@app.get("/api/drivers")
def get_drivers():
    return storage.get_all_drivers()

@app.post("/api/drivers")
def create_driver(driver: Driver, background_tasks: BackgroundTasks):
    doc_id = storage.add_driver(driver.model_dump() if hasattr(driver, 'model_dump') else driver.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"doc_id": doc_id, "status": "created"}

@app.delete("/api/drivers/{doc_id}")
def delete_driver(doc_id: int, background_tasks: BackgroundTasks):
    storage.delete_driver(doc_id)
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "deleted"}

# --- SSE Stream API ---
@app.get("/api/stream")
async def stream_events():
    async def event_generator():
        last_seen = LAST_UPDATE_TIME
        last_ping = time.time()
        try:
            while True:
                await asyncio.sleep(1)
                now = time.time()
                if LAST_UPDATE_TIME > last_seen:
                    last_seen = LAST_UPDATE_TIME
                    yield "data: update\n\n"
                    last_ping = now
                elif now - last_ping > 15:
                    # SSE keep-alive comment
                    yield ": ping\n\n"
                    last_ping = now
        except asyncio.CancelledError:
            pass
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Passengers API ---
@app.get("/api/passengers")
def get_passengers():
    return storage.get_all_passengers()

@app.post("/api/passengers")
def create_passenger(passenger: Passenger, background_tasks: BackgroundTasks):
    doc_id = storage.add_passenger(passenger.model_dump() if hasattr(passenger, 'model_dump') else passenger.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/passengers/{doc_id}")
def update_passenger(doc_id: int, passenger: Passenger, background_tasks: BackgroundTasks):
    storage.update_passenger(doc_id, passenger.model_dump() if hasattr(passenger, 'model_dump') else passenger.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "updated"}

@app.delete("/api/passengers/{doc_id}")
def delete_passenger(doc_id: int, background_tasks: BackgroundTasks):
    storage.delete_passenger(doc_id)
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "deleted"}

# --- Rules API ---
@app.get("/api/rules")
def get_rules():
    return storage.get_all_rules()

@app.post("/api/rules")
def create_rule(rule: Rule, background_tasks: BackgroundTasks):
    doc_id = storage.add_rule(rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/rules/{doc_id}")
def update_rule(doc_id: int, rule: Rule, background_tasks: BackgroundTasks):
    storage.update_rule(doc_id, rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "updated"}

@app.delete("/api/rules/{doc_id}")
def delete_rule(doc_id: int, background_tasks: BackgroundTasks):
    storage.delete_rule(doc_id)
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "deleted"}

# --- Errand Rules API ---
@app.get("/api/errand_rules")
def get_errand_rules():
    return storage.get_all_errand_rules()

@app.post("/api/errand_rules")
def create_errand_rule(rule: ErrandRule, background_tasks: BackgroundTasks):
    doc_id = storage.add_errand_rule(rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/errand_rules/{doc_id}")
def update_errand_rule(doc_id: int, rule: ErrandRule, background_tasks: BackgroundTasks):
    storage.update_errand_rule(doc_id, rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "updated"}

@app.delete("/api/errand_rules/{doc_id}")
def delete_errand_rule(doc_id: int, background_tasks: BackgroundTasks):
    storage.delete_errand_rule(doc_id)
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "deleted"}

# --- Errands API ---
def check_past_due_errands():
    errands = storage.get_all_errands()
    import time
    now_ts = time.time()
    for e in errands:
        if not e.get('is_completed') and e.get('status', 'pending') != 'past_due':
            lse = e.get('last_scheduled_end')
            if lse and lse < now_ts:
                e['status'] = 'past_due'
                storage.update_errand(e['doc_id'], e)

@app.get("/api/download_db")
def download_db():
    import zipfile
    import io
    import os
    from fastapi.responses import StreamingResponse
    
    data_dir = "/data" if os.path.exists("/data") else "data"
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(data_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, data_dir)
                zip_file.write(file_path, arcname)
    
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=chauffeur_data.zip"}
    )

@app.get("/api/errands")
def get_errands():
    check_past_due_errands()
    raw = storage.get_all_errands()
    errand_schedules = storage.get_all_scheduled_errands()
            
    res = []
    for e in raw:
        obj = Errand(**e).model_dump() if hasattr(Errand(**e), 'model_dump') else Errand(**e).dict()
        if obj['id'] in errand_schedules:
            obj['scheduled_start'] = errand_schedules[obj['id']]
        res.append(obj)
    return res

@app.post("/api/errands")
def create_errand(errand: Errand, background_tasks: BackgroundTasks):
    errand_dict = errand.model_dump() if hasattr(errand, 'model_dump') else errand.dict()
    
    # Apply Errand Rules
    rules = storage.get_all_errand_rules()
    errand_text = (errand.title + " " + (errand.tags and " ".join(errand.tags) or "")).lower()
    
    for r in rules:
        if not r.get('is_enabled', True): continue
        ctype = r.get('constraint_type', 'driver_assignment')
        match = False
        
        if ctype == 'grouping':
            filter_sets = r.get('filter_sets', [])
            if not filter_sets: continue
            
            for fs in filter_sets:
                fs_match = True
                
                # Check keywords in filter set
                kws = fs.get('keywords', [])
                if kws:
                    match_all = fs.get('keywords_match_all', False)
                    if match_all:
                        if not all(kw.lower() in errand_text for kw in kws): fs_match = False
                    else:
                        if not any(kw.lower() in errand_text for kw in kws): fs_match = False
                
                # Check location in filter set
                fs_loc = fs.get('location')
                if fs_loc and fs_match:
                    if fs_loc.lower() not in errand.location.lower():
                        fs_match = False
                
                if fs_match and (kws or fs_loc):
                    match = True
                    break
        else:
            match = True
            # Check Keywords
            kws = r.get('keywords', [])
            if kws:
                match_all = r.get('keywords_match_all', False)
                if match_all:
                    if not all(kw.lower() in errand_text for kw in kws): match = False
                else:
                    if not any(kw.lower() in errand_text for kw in kws): match = False
                    
            # Check Location
            rule_loc = r.get('location')
            if rule_loc and match:
                if rule_loc.lower() not in errand.location.lower():
                    match = False
                    
            if not (kws or rule_loc): match = False
                
        if match:
            if ctype == 'driver_assignment':
                if r.get('allowed_drivers') and not errand_dict.get('allowed_drivers'): errand_dict['allowed_drivers'] = r['allowed_drivers']
                if r.get('required_drivers') and not errand_dict.get('required_drivers'): errand_dict['required_drivers'] = r['required_drivers']
                if r.get('prohibited_drivers') and not errand_dict.get('prohibited_drivers'): errand_dict['prohibited_drivers'] = r['prohibited_drivers']
            elif ctype == 'passenger_assignment':
                if r.get('allowed_passengers') and not errand_dict.get('allowed_passengers'): errand_dict['allowed_passengers'] = r['allowed_passengers']
                if r.get('required_passengers') and not errand_dict.get('required_passengers'): errand_dict['required_passengers'] = r['required_passengers']
                if r.get('prohibited_passengers') and not errand_dict.get('prohibited_passengers'): errand_dict['prohibited_passengers'] = r['prohibited_passengers']
            elif ctype == 'buffer_tolerance':
                if r.get('tolerance_mins') and not errand_dict.get('tolerance_mins'): errand_dict['tolerance_mins'] = r['tolerance_mins']
                if r.get('buffer_mins') and not errand_dict.get('buffer_mins'): errand_dict['buffer_mins'] = r['buffer_mins']
            elif ctype == 'time_of_day':
                if r.get('time_window_start') and not errand_dict.get('time_window_start'): errand_dict['time_window_start'] = r['time_window_start']
                if r.get('time_window_end') and not errand_dict.get('time_window_end'): errand_dict['time_window_end'] = r['time_window_end']
            elif ctype == 'grouping':
                if not errand_dict.get('group_id'): errand_dict['group_id'] = r.get('id')

    doc_id = storage.add_errand(errand_dict)
    background_tasks.add_task(trigger_background_refresh)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/errands/{doc_id}")
def update_errand(doc_id: int, errand: Errand, background_tasks: BackgroundTasks):
    # Check for recurrence trigger
    old_e_list = [e for e in storage.get_all_errands() if e['doc_id'] == doc_id]
    if old_e_list:
        old_e = old_e_list[0]
        if not old_e.get('is_completed') and errand.is_completed and errand.recurrence_rule:
            new_e = errand.model_dump() if hasattr(errand, 'model_dump') else errand.dict()
            import uuid
            import time
            new_e['id'] = uuid.uuid4().hex
            new_e['is_completed'] = False
            new_e['status'] = 'pending'
            new_e['last_scheduled_end'] = None
            new_e['created_at'] = time.time()
            if 'doc_id' in new_e:
                del new_e['doc_id']
            storage.add_errand(new_e)

    storage.update_errand(doc_id, errand.model_dump() if hasattr(errand, 'model_dump') else errand.dict())
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "updated"}

@app.delete("/api/errands/{doc_id}")
def delete_errand(doc_id: int, background_tasks: BackgroundTasks):
    storage.delete_errand(doc_id)
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "deleted"}

analysis_tasks = {}

@app.post("/api/rules/analyze-overrides/start")
def start_analyze_overrides(background_tasks: BackgroundTasks):
    import uuid
    task_id = str(uuid.uuid4())
    analysis_tasks[task_id] = {"status": "running", "logs": []}
    background_tasks.add_task(_run_analysis_task, task_id)
    return {"task_id": task_id}

@app.get("/api/rules/analyze-overrides/status/{task_id}")
def get_analyze_status(task_id: str):
    return analysis_tasks.get(task_id, {"status": "not_found"})

def log_task(task_id: str, msg: str):
    import datetime
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    log_line = f"[{ts}] {msg}"
    logger.info(f"[Task {task_id}] {msg}")
    if task_id in analysis_tasks:
        analysis_tasks[task_id].setdefault('logs', []).append(log_line)

def _run_analysis_task(task_id: str):
    log_task(task_id, "Starting analysis task...")
    try:
        from services.llm import identify_override_patterns, deduce_rules_from_context
        import json
        
        settings = storage.get_settings()
        llm_provider = settings.get('llm_provider', 'gemini')
        llm_url = settings.get('llm_ollama_url', 'http://localhost:11434')
        llm_api_key = settings.get('llm_gemini_api_key', '')
        llm_model = settings.get('llm_gemini_model', 'gemini-3.5-flash') if llm_provider == 'gemini' else settings.get('llm_ollama_model', 'qwen2.5:7b')
        
        # 1. Fetch Overrides
        log_task(task_id, "Fetching overrides from database...")
        raw_overrides = storage.get_all_overrides()
        
        # Filter out legacy overrides that don't have date_str/event_title
        overrides = [o for o in raw_overrides if o.get('date_str') and o.get('event_title')]
        
        log_task(task_id, f"Found {len(overrides)} valid overrides to analyze.")
        if not overrides:
            analysis_tasks[task_id] = {"status": "completed", "result": {"new_rules_count": 0, "new_priority_rules_count": 0}}
            return
            
        # Enrich overrides with event titles and cache schedules
        enriched_overrides = []
        schedule_cache = {}
        for o in overrides:
            date_str = o.get('date_str')
            event_id = o.get('event_id')
            if date_str not in schedule_cache:
                try:
                    schedule_cache[date_str] = _refresh_schedule_logic_impl(date_str, date_str, force_refresh=False, ignore_overrides=True)
                except Exception as e:
                    logger.error(f"Failed to fetch schedule context for {date_str}: {e}")
                    schedule_cache[date_str] = {'events': []}
            
            event_title = o.get('event_title')
            if not event_title:
                event_title = event_id
                for evt in schedule_cache[date_str].get('events', []):
                    if hasattr(evt, 'dict'): evt = evt.dict()
                    elif hasattr(evt, 'model_dump'): evt = evt.model_dump()
                    
                    if (evt.get('id') == event_id or 
                        evt.get('recurring_event_id') == event_id or 
                        evt.get('original_event_id') == event_id or 
                        event_id in (evt.get('source_event_ids') or [])):
                        event_title = evt.get('title')
                        break
                    
            enriched_overrides.append({
                "date_str": date_str,
                "event_id": event_id,
                "event_title": event_title,
                "driver_id": o.get('driver_id')
            })
            
        # Phase 1: Map
        try:
            log_task(task_id, "Phase 1: Calling LLM to identify pattern clusters...")
            clusters = identify_override_patterns(llm_provider, llm_url, llm_api_key, llm_model, enriched_overrides)
            log_task(task_id, f"Phase 1 Complete: LLM identified {len(clusters)} clusters.")
        except Exception as e:
            logger.error(f"Failed to identify override patterns: {e}")
            log_task(task_id, f"Error identifying patterns: {e}")
            analysis_tasks[task_id] = {"status": "failed", "error": f"Failed to identify override patterns: {str(e)}"}
            return
            
        if not clusters:
            analysis_tasks[task_id] = {"status": "completed", "result": {"new_rules_count": 0, "new_priority_rules_count": 0}}
            return
            
        passengers_data = storage.get_all_passengers()
        existing_rules = storage.get_all_rules()
        existing_priority_rules = storage.get_all_priority_rules()
        
        new_rules_count = 0
        new_priority_rules_count = 0
        
        for i, cluster in enumerate(clusters):
            log_task(task_id, f"Phase 2: Analyzing cluster {i+1}/{len(clusters)}: {cluster.get('description')}")
            dates = cluster.get('dates', [])
            if not dates: continue
            
            # 2. Reconstruct Context
            original_schedules_context = f"Cluster: {cluster.get('description')}\n\n"
            modified_schedules_context = f"Cluster: {cluster.get('description')}\n\n"
            
            for date_str in dates:
                original_schedules_context += f"--- Schedule for {date_str} ---\n"
                modified_schedules_context += f"--- Schedule for {date_str} ---\n"
                
                try:
                    # Get Original Schedule (ignoring overrides)
                    res_orig = schedule_cache.get(date_str, {'events': []})
                    for evt in res_orig.get('events', []):
                        if hasattr(evt, 'dict'): evt = evt.dict()
                        elif hasattr(evt, 'model_dump'): evt = evt.model_dump()
                        driver_name = evt.get('driver', {}).get('name', 'Unassigned')
                        original_schedules_context += f"{evt.get('time_start')} - {evt.get('time_end')} | {evt.get('title')} | Assigned: {driver_name} | Location: {evt.get('location')}\n"
                        
                    # Get Modified Schedule (with overrides)
                    res_mod = _refresh_schedule_logic_impl(date_str, date_str, force_refresh=False, ignore_overrides=False)
                    for evt in res_mod.get('events', []):
                        if hasattr(evt, 'dict'): evt = evt.dict()
                        elif hasattr(evt, 'model_dump'): evt = evt.model_dump()
                        driver_name = evt.get('driver', {}).get('name', 'Unassigned')
                        modified_schedules_context += f"{evt.get('time_start')} - {evt.get('time_end')} | {evt.get('title')} | Assigned: {driver_name} | Location: {evt.get('location')}\n"
                except Exception as e:
                    logger.error(f"Failed to fetch schedule context for {date_str}: {e}")
                    
            # Phase 2: Reduce
            try:
                log_task(task_id, f"Asking LLM to deduce logical rules for cluster '{cluster.get('description')}'...")
                deduced_data = deduce_rules_from_context(llm_provider, llm_url, llm_api_key, llm_model, cluster, original_schedules_context, modified_schedules_context, passengers_data)
                log_task(task_id, f"LLM proposed {len(deduced_data.get('rules', []))} rules and {len(deduced_data.get('priority_rules', []))} priority rules.")
                
                # Phase 3: Duplicate Detection & Collect
                def is_duplicate(new_r, existing_list, is_priority=False):
                    for er in existing_list:
                        if er.get('constraint_type') == new_r.get('constraint_type') and er.get('driver_id') == new_r.get('driver_id') and set(er.get('keywords', [])) == set(new_r.get('keywords', [])) and set(er.get('passenger_ids', [])) == set(new_r.get('passenger_ids', [])) and er.get('location') == new_r.get('location') and set(er.get('days_of_week', [])) == set(new_r.get('days_of_week', [])) and er.get('time_start') == new_r.get('time_start') and er.get('time_end') == new_r.get('time_end'):
                            if is_priority and er.get('weight_modifier') != new_r.get('weight_modifier'):
                                continue
                            return True
                    return False
                    
                cluster_rules = []
                cluster_priority_rules = []
                    
                for r in deduced_data.get('rules', []):
                    if not is_duplicate(r, existing_rules):
                        cluster_rules.append(r)
                        existing_rules.append(r) # Add to temporary list so we don't duplicate within the same session
                        new_rules_count += 1
                        
                for pr in deduced_data.get('priority_rules', []):
                    if not is_duplicate(pr, existing_priority_rules, is_priority=True):
                        cluster_priority_rules.append(pr)
                        existing_priority_rules.append(pr)
                        new_priority_rules_count += 1
                        
                cluster['proposed_rules'] = cluster_rules
                cluster['proposed_priority_rules'] = cluster_priority_rules
            except Exception as e:
                logger.error(f"Failed to deduce rules for cluster {cluster.get('description')}: {e}")
                
        # Map passenger IDs to names for UI display
        passenger_map = {}
        for p in passengers_data:
            p_name = p.get('name', p.get('id'))
            for cid in p.get('calendar_ids', [p.get('id')]):
                passenger_map[cid] = p_name

        drivers_data = storage.get_all_drivers()
        driver_map = {d.get('id'): d.get('name', d.get('id')) for d in drivers_data}

        for cluster in clusters:
            for r in cluster.get('proposed_rules', []):
                r['passenger_names'] = [passenger_map.get(pid, pid) for pid in r.get('passenger_ids', [])]
                r['driver_name'] = driver_map.get(r.get('driver_id'), r.get('driver_id'))
            for pr in cluster.get('proposed_priority_rules', []):
                pr['passenger_names'] = [passenger_map.get(pid, pid) for pid in pr.get('passenger_ids', [])]
                pr['driver_name'] = driver_map.get(pr.get('driver_id'), pr.get('driver_id'))

        log_task(task_id, f"Analysis complete! Generated {new_rules_count} unique rules and {new_priority_rules_count} unique priority rules.")
        analysis_tasks[task_id] = {
            "status": "completed", 
            "result": {
                "new_rules_count": new_rules_count, 
                "new_priority_rules_count": new_priority_rules_count, 
                "clusters": clusters
            }
        }
    except Exception as e:
        import traceback
        logger.error(f"Analyze overrides failed with {e}\n{traceback.format_exc()}")
        log_task(task_id, f"Fatal Error: {str(e)}")
        analysis_tasks[task_id] = {"status": "failed", "error": str(e), "traceback": traceback.format_exc()}

# --- Bulk Rules API ---
from pydantic import BaseModel
from typing import List

class BulkRulesPayload(BaseModel):
    rules: List[dict]
    priority_rules: List[dict]

@app.post("/api/rules/bulk-add")
def bulk_add_rules(payload: BulkRulesPayload, background_tasks: BackgroundTasks):
    for r in payload.rules:
        storage.add_rule(r)
    for pr in payload.priority_rules:
        storage.add_priority_rule(pr)
        
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "success", "message": f"Added {len(payload.rules)} rules and {len(payload.priority_rules)} priority rules."}

# --- Priority Rules API ---
@app.get("/api/priority_rules")
def get_priority_rules():
    return storage.get_all_priority_rules()

@app.post("/api/priority_rules")
def create_priority_rule(rule: PriorityRule, background_tasks: BackgroundTasks):
    doc_id = storage.add_priority_rule(rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/priority_rules/{doc_id}")
def update_priority_rule(doc_id: int, rule: PriorityRule, background_tasks: BackgroundTasks):
    storage.update_priority_rule(doc_id, rule.model_dump() if hasattr(rule, 'model_dump') else rule.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "updated"}

@app.delete("/api/priority_rules/{doc_id}")
def delete_priority_rule(doc_id: int, background_tasks: BackgroundTasks):
    storage.delete_priority_rule(doc_id)
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "deleted"}

# --- Themes API ---
@app.get("/api/themes")
def get_themes():
    return storage.get_all_themes()

@app.post("/api/themes")
def create_theme(theme_data: dict, background_tasks: BackgroundTasks):
    doc_id = storage.add_theme(theme_data)
    background_tasks.add_task(refresh_schedule_logic)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/themes/{doc_id}")
def update_theme(doc_id: int, theme_data: dict, background_tasks: BackgroundTasks):
    storage.update_theme(doc_id, theme_data)
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "updated"}

@app.delete("/api/themes/{doc_id}")
def delete_theme(doc_id: int, background_tasks: BackgroundTasks):
    storage.delete_theme(doc_id)
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "deleted"}

# --- Overrides API ---
@app.get("/api/overrides")
def get_overrides():
    return storage.get_all_overrides()

@app.post("/api/overrides")
def create_override(override: ManualOverride, background_tasks: BackgroundTasks, draft: bool = False):
    doc_id = storage.add_override(override.model_dump() if hasattr(override, 'model_dump') else override.dict())
    if not draft:
        background_tasks.add_task(trigger_background_refresh)
    return {"doc_id": doc_id, "status": "created"}

@app.delete("/api/overrides/{doc_id}")
def delete_override(doc_id: int, background_tasks: BackgroundTasks, draft: bool = False):
    storage.delete_override(doc_id)
    if not draft:
        background_tasks.add_task(trigger_background_refresh)
    return {"status": "deleted"}

@app.delete("/api/overrides/event/{event_id}")
def delete_override_by_event(event_id: str, background_tasks: BackgroundTasks, draft: bool = False):
    storage.delete_override_by_event(event_id)
    if not draft:
        background_tasks.add_task(trigger_background_refresh)
    return {"status": "deleted"}

# --- Event Configs API ---
@app.post("/api/events/config/{google_id}")
def update_event_config(google_id: str, config_data: dict, background_tasks: BackgroundTasks):
    storage.set_event_config(google_id, config_data)
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "updated"}

@app.delete("/api/events/config/{google_id}")
def delete_event_config(google_id: str, background_tasks: BackgroundTasks):
    storage.delete_event_config(google_id)
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "deleted"}

# --- Settings API ---
@app.get("/api/settings")
def get_settings():
    settings = storage.get_settings()
    
    # Merge map options from options.json so UI reflects effective settings
    import json
    options_file = '/data/options.json'
    if os.path.exists(options_file):
        try:
            with open(options_file, 'r') as f:
                options = json.load(f)
            for k in ['disable_mapbox_matrix', 'disable_mapbox_directions', 'disable_mapbox', 'disable_mapbox_category',
                      'mapbox_matrix_limit', 'mapbox_directions_limit', 
                      'mapbox_geocode_limit', 'mapbox_searchbox_limit', 'mapbox_category_limit']:
                if k not in settings and k in options:
                    settings[k] = options[k]
        except Exception:
            pass
            
    settings['is_home_assistant'] = os.path.exists('/data/options.json')
    return settings

@app.post("/api/settings")
def update_settings(settings: Settings, background_tasks: BackgroundTasks):
    storage.update_settings(settings.model_dump() if hasattr(settings, 'model_dump') else settings.dict())
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "updated"}

class ChatMessagePayload(BaseModel):
    message: str
    source: Optional[str] = "admin"
    driver_id: Optional[str] = None

@app.post("/api/chat")
def handle_chat(payload: ChatMessagePayload):
    from services.llm import agentic_chat_loop
    try:
        reply = agentic_chat_loop(payload.message, source=payload.source, driver_id=payload.driver_id)
        return {"reply": reply}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.get("/api/chat/history")
def get_chat_history():
    return {"history": storage.get_chat_history()}

@app.delete("/api/chat/history")
def clear_chat_history():
    storage.clear_chat_history()
    return {"status": "cleared"}

class LLMTestPayload(BaseModel):
    provider: str
    url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None

@app.post("/api/settings/test_llm")
def test_llm(payload: LLMTestPayload):
    from services.llm import test_llm_connection
    success, message = test_llm_connection(
        provider=payload.provider,
        url=payload.url,
        api_key=payload.api_key,
        model=payload.model
    )
    return {"success": success, "message": message}

@app.post("/api/settings/generate_ai_rules")
def generate_ai_rules(background_tasks: BackgroundTasks):
    from services.llm import generate_rules_from_philosophy
    
    settings = storage.get_settings()
    provider = settings.get('llm_provider', '')
    if not provider:
        return {"success": False, "message": "AI Assistant is not configured. Please select a provider first."}
        
    url = settings.get('llm_ollama_url', 'http://localhost:11434')
    api_key = settings.get('llm_gemini_api_key', '')
    if provider == 'gemini':
        model = settings.get('llm_gemini_model', 'gemini-3.5-flash')
    else:
        model = settings.get('llm_ollama_model', 'qwen2.5:7b')
    philosophy = settings.get('family_philosophy', '')
    
    if not philosophy.strip():
        return {"success": False, "message": "Family Philosophy is empty. Please enter your scheduling philosophy first."}
        
    drivers = storage.get_all_drivers()
    passengers = storage.get_all_passengers()
    
    try:
        feedback_docs = storage.get_recent_ai_feedback(limit=15)
        recent_feedback = [f.get('context', '') for f in feedback_docs if f.get('context')]

        rules, priority_rules, themes, raw_log = generate_rules_from_philosophy(
            provider=provider,
            url=url,
            api_key=api_key,
            model=model,
            philosophy=philosophy,
            drivers=drivers,
            passengers=passengers,
            feedback=recent_feedback
        )
        
        # Save to database
        with storage.db_lock:
            # 1. Remove all old AI generated rules
            from tinydb import Query
            storage.rules_table.remove(Query().is_ai_generated == True)
            storage.priority_rules_table.remove(Query().is_ai_generated == True)
            storage.themes_table.truncate()
            
            # 2. Insert new ones
            for r in rules:
                storage.rules_table.insert(r)
            for pr in priority_rules:
                storage.priority_rules_table.insert(pr)
            for t in themes:
                storage.themes_table.insert(t)
                
            # 3. Clear schedule caches so solver reruns on next fetch
            storage.custom_schedules_table.truncate()
            storage.mark_all_daily_schedules_dirty()
            storage.cache_table.truncate()
            
        # Trigger background schedule solve
        background_tasks.add_task(trigger_background_refresh)
        
        msg = f"Successfully generated {len(rules)} rules, {len(priority_rules)} priority rules, and {len(themes)} themes!"
        if len(themes) < 2:
            msg = f"WARNING: Generated {len(rules)} rules, but only {len(themes)} themes! The AI evaluation requires at least 2 themes to compare options."
        return {
            "success": True if len(themes) > 0 else False, 
            "message": msg,
            "rules_count": len(rules),
            "priority_rules_count": len(priority_rules),
            "themes_count": len(themes)
        }
    except Exception as e:
        logger.error(f"AI Rule generation failed: {e}", exc_info=True)
        return {"success": False, "message": str(e)}

class LLMRefinePayload(BaseModel):
    text: str
    context_type: str

@app.post("/api/settings/refine_text")
def refine_text(payload: LLMRefinePayload):
    from services.llm import refine_scheduling_text
    
    settings = storage.get_settings()
    provider = settings.get('llm_provider', '')
    if not provider:
        return {"success": False, "message": "AI Assistant is not configured. Please select a provider in settings first."}
        
    url = settings.get('llm_ollama_url', 'http://localhost:11434')
    api_key = settings.get('llm_gemini_api_key', '')
    if provider == 'gemini':
        model = settings.get('llm_gemini_model', 'gemini-3.5-flash')
    else:
        model = settings.get('llm_ollama_model', 'qwen2.5:7b')
    
    try:
        refined = refine_scheduling_text(
            provider=provider,
            url=url,
            api_key=api_key,
            model=model,
            text=payload.text,
            context_type=payload.context_type
        )
        return {"success": True, "refined_text": refined}
    except Exception as e:
        logger.error(f"AI Text refinement failed: {e}", exc_info=True)
        return {"success": False, "message": str(e)}

class AIFeedbackPayload(BaseModel):
    context: str

@app.post("/api/settings/ai_feedback")
def submit_ai_feedback(payload: AIFeedbackPayload):
    storage.add_ai_feedback(payload.context)
    return {"status": "saved"}

@app.delete("/api/cache")
def clear_caches():
    with storage.db_lock:
        storage.distance_cache_table.truncate()
        storage.cache_table.truncate()
        storage.daily_schedules_table.truncate()
        storage.custom_schedules_table.truncate()
    return {"status": "cleared"}

@app.get("/api/maps/stats")
def get_maps_stats():
    import datetime
    current_month = datetime.datetime.now().strftime("%Y-%m")
    
    stats = {
        "matrix": {
            "monthly": storage.get_mapbox_usage(current_month, 'matrix'),
            "rolling_24h": storage.get_rolling_usage('matrix', 86400),
            "rpm": storage.get_rolling_usage('matrix', 60),
            "limit": maps.get_map_option('mapbox_matrix_limit', 90000),
            "disabled": maps.get_map_option('disable_mapbox_matrix', False)
        },
        "directions": {
            "monthly": storage.get_mapbox_usage(current_month, 'directions'),
            "rolling_24h": storage.get_rolling_usage('directions', 86400),
            "rpm": storage.get_rolling_usage('directions', 60),
            "limit": maps.get_map_option('mapbox_directions_limit', 90000),
            "disabled": maps.get_map_option('disable_mapbox_directions', False)
        },
        "geocode": {
            "monthly": storage.get_mapbox_usage(current_month, 'geocode'),
            "rolling_24h": storage.get_rolling_usage('geocode', 86400),
            "rpm": storage.get_rolling_usage('geocode', 60),
            "limit": maps.get_map_option('mapbox_geocode_limit', 90000),
            "disabled": maps.get_map_option('disable_mapbox', False)
        },
        "searchbox": {
            "monthly": storage.get_mapbox_usage(current_month, 'searchbox_sessions'),
            "rolling_24h": storage.get_rolling_usage('searchbox_sessions', 86400),
            "rpm": storage.get_rolling_usage('searchbox_sessions', 60),
            "limit": maps.get_map_option('mapbox_searchbox_limit', 500),
            "disabled": maps.get_map_option('disable_mapbox', False)
        },
        "category": {
            "monthly": storage.get_mapbox_usage(current_month, 'category'),
            "rolling_24h": storage.get_rolling_usage('category', 86400),
            "rpm": storage.get_rolling_usage('category', 60),
            "limit": maps.get_map_option('mapbox_category_limit', 45000),
            "disabled": maps.get_map_option('disable_mapbox_category', False) or maps.get_map_option('disable_mapbox', False)
        }
    }
    
    return {"status": "success", "month": current_month, "stats": stats}

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
        return {"status": "updated"}
    except Exception as e:
        return {"error": str(e)}

# --- Maps API ---
@app.get("/api/maps/route_info")
def get_route_info(origin: str, destination: str):
    mins = maps.get_travel_time_minutes(origin, destination)
    return {"duration": f"{mins * 60}s", "distanceMeters": mins * 1000}  # Mock distance

@app.get("/api/places/autocomplete")
def get_places_autocomplete(input: str, session_token: str = None):
    suggestions = maps.autocomplete_location(input, session_token)
    return {"suggestions": suggestions}

@app.get("/api/places/retrieve")
def get_places_retrieve(mapbox_id: str, session_token: str):
    result = maps.retrieve_location(mapbox_id, session_token)
    if result:
        return result
    from fastapi import HTTPException
    raise HTTPException(status_code=400, detail="Failed to retrieve location")

from functools import lru_cache

@lru_cache(maxsize=128)
def _fetch_unsplash_url(query: str, api_key: str) -> str:
    import urllib.parse
    import requests
    
    fallback_url = "https://images.unsplash.com/photo-1499856871958-5b9627545d1a?q=80&w=1920&auto=format&fit=crop"
    if not query:
        return fallback_url
        
    if 'paris' in query.lower():
        fallback_url = "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?q=80&w=1920&auto=format&fit=crop"
    elif 'tokyo' in query.lower():
        fallback_url = "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?q=80&w=1920&auto=format&fit=crop"
    elif 'london' in query.lower():
        fallback_url = "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?q=80&w=1920&auto=format&fit=crop"

    if not api_key:
        print("Unsplash API: No API key found in options")
    else:
        encoded_query = urllib.parse.quote(query)
        try:
            api_url = f"https://api.unsplash.com/search/photos?query={encoded_query}&orientation=landscape&per_page=1"
            print(f"Unsplash API Request: {api_url}")
            res = requests.get(
                api_url,
                headers={"Authorization": f"Client-ID {api_key}"},
                timeout=5
            )
            print(f"Unsplash API Response: {res.status_code} - {res.text[:200]}")
            if res.ok:
                data = res.json()
                if data.get("results") and len(data["results"]) > 0:
                    return data["results"][0]["urls"]["regular"]
                else:
                    print(f"Unsplash API: No results found for query '{query}'")
        except Exception as e:
            print(f"Unsplash API Error: {e}")

    return fallback_url

@app.get("/api/unsplash/background")
def get_unsplash_background(query: str):
    # Uses official Unsplash API if a key is provided in Addon Config
    api_key = maps.get_map_option('unsplash_api_key', None)
    
    url = _fetch_unsplash_url(query, api_key)
    
    return RedirectResponse(url=url, headers={"Cache-Control": "public, max-age=86400"})


# --- Schedule API ---
import hashlib

def hash_events(events_list):
    sorted_events = sorted(events_list, key=lambda e: getattr(e, 'id', ''))
    parts = []
    for e in sorted_events:
        parts.append(f"{getattr(e, 'id', '')}|{getattr(e, 'start', '')}|{getattr(e, 'end', '')}|{getattr(e, 'location', '')}|{getattr(e, 'title', '')}")
    return hashlib.sha256("||".join(parts).encode('utf-8')).hexdigest()

import threading

class AbortRefreshException(Exception):
    pass

class ScheduleCoordinator:
    def __init__(self):
        self.lock = threading.RLock()
        self.is_running = False
        self.pending_refresh = False
        self.pending_args = None
        self.current_args = None
        self.solving_dates = set()

    def start_solving(self, dates):
        with self.lock:
            self.solving_dates.update(dates)

    def finish_solving(self, date_str):
        with self.lock:
            self.solving_dates.discard(date_str)

    def get_solving_dates(self):
        with self.lock:
            return list(self.solving_dates)

    def clear_solving_dates(self):
        with self.lock:
            self.solving_dates.clear()

schedule_coordinator = ScheduleCoordinator()

def check_abort_refresh():
    if schedule_coordinator.pending_refresh:
        raise AbortRefreshException()

def trigger_background_refresh(start_date_str=None, end_date_str=None, force_refresh=False, draft=False):
    # Simply run the logic concurrently
    try:
        refresh_schedule_logic(start_date_str, end_date_str, force_refresh, draft)
    except Exception as e:
        logger.error(f"Error in background schedule run: {e}", exc_info=True)

import threading

def refresh_schedule_logic(start_date_str=None, end_date_str=None, force_refresh=False, draft=False):
    try:
        res = _refresh_schedule_logic_impl(start_date_str, end_date_str, force_refresh, draft)
        global LAST_UPDATE_TIME
        LAST_UPDATE_TIME = time.time()
        return res
    except Exception as e:
        logger.error("Fatal error during schedule generation", exc_info=True)
        import traceback
        return {"error": "Fatal Error: " + str(e), "traceback": traceback.format_exc()}

def _refresh_schedule_logic_impl(start_date_str=None, end_date_str=None, force_refresh=False, draft=False, ignore_overrides=False):
    settings = storage.get_settings()
    calendar_ids = settings.get("calendar_ids", [])
    
    errands = storage.get_all_errands()
        
    drivers_data = storage.get_all_drivers()
    # Provide default values for existing drivers to pass Pydantic validation
    for d in drivers_data:
        if 'group' not in d: d['group'] = 'primary'
        if 'priority_index' not in d: d['priority_index'] = 1
        if 'calendar_ids' not in d: d['calendar_ids'] = []
        
    drivers = [Driver(**d) for d in drivers_data if not d.get('is_disabled', False)]
    
    driver_calendar_map = {}
    driver_calendar_ids = set()
    for d in drivers:
        for cid in d.calendar_ids:
            if cid and cid.strip():
                c = cid.strip()
                driver_calendar_ids.add(c)
                driver_calendar_map[c] = d
                
    passengers_data = storage.get_all_passengers()
    passengers = [Passenger(**p) for p in passengers_data]
    
    passenger_calendar_map = {}
    passenger_calendar_ids = set()
    for p in passengers:
        passenger_calendar_map[str(p.id)] = p
        for cid in p.calendar_ids:
            if cid and cid.strip():
                c = cid.strip()
                passenger_calendar_ids.add(c)
                passenger_calendar_map[c] = p
                
    all_cals_to_fetch = sorted(list(set(calendar_ids) | driver_calendar_ids | passenger_calendar_ids))
    
    # If there are no calendars to fetch at all, return an error
    if not all_cals_to_fetch:
        return {"error": "No calendar IDs configured in settings, drivers, or passengers."}
    
    # Fetch events dynamically based on the days_to_show settings
    days_to_fetch = int(settings.get('days_to_show', 30))

    
    import difflib
    
    import re
    text_hashtag_cache = {}
    def fuzzy_has_hashtag(text, target_tag):
        if not target_tag or not text: return False
        
        if text not in text_hashtag_cache:
            clean_text = re.sub(r'<[^>]+>', ' ', text)
            words = [w.lower().strip('.,;?!()[]{}""\'\'') for w in clean_text.split()]
            text_hashtag_cache[text] = {w for w in words if w.startswith('#')}
            
        target = target_tag.lower().strip('.,;?!()[]{}""\'\'')
        return target in text_hashtag_cache[text]

    try:
        raw_events = calendar.fetch_upcoming_events(all_cals_to_fetch, days=days_to_fetch, start_date_str=start_date_str, end_date_str=end_date_str)
        
        trip_hashtags = settings.get('trip_hashtags', [])
        trip_events = []
        
        all_fetched_events = []
        for e in raw_events:
            is_trip = False
            if getattr(e, 'location', ''):
                if any(fuzzy_has_hashtag(e.title, t) or fuzzy_has_hashtag(e.description, t) for t in trip_hashtags):
                    is_trip = True
                    e.event_type = 'background_trip'
                    
            if getattr(e, 'all_day', False) and not is_trip:
                continue
                
            all_fetched_events.append(e)
            
        pass

    except Exception as e:
        return {"error": f"Failed to fetch events: {str(e)}"}
        
    # Removed global hash check. We now do day-by-day hashing and caching below.
    events = []
    all_events_for_ui = {} # To avoid duplicates in payload

    driver_events_map = {d.id: [] for d in drivers}
    driver_events_ids = {d.id: [] for d in drivers}

    rules_data = storage.get_all_rules()
    priority_rules_data = storage.get_all_priority_rules()
    overrides_data = [] if ignore_overrides else storage.get_all_overrides()

    enable_standard_rules = settings.get("enable_standard_rules", True)
    enable_ai_rules = settings.get("enable_ai_rules", True)

    rules = []
    for r in rules_data:
        try:
            rule_obj = Rule(**r)
            if not rule_obj.is_enabled: continue
            if rule_obj.is_ai_generated and not enable_ai_rules: continue
            if not rule_obj.is_ai_generated and not enable_standard_rules: continue
            rules.append(rule_obj)
        except Exception as err:
            logger.warning(f"Skipping invalid rule from database: {err}. Rule data: {r}")

    priority_rules = []
    enable_standard_priority_rules = settings.get("enable_standard_priority_rules", True)
    enable_ai_priority_rules = settings.get("enable_ai_priority_rules", True)
    for pr in priority_rules_data:
        try:
            p_rule_obj = PriorityRule(**pr)
            if not p_rule_obj.is_enabled: continue
            if p_rule_obj.is_ai_generated and not enable_ai_priority_rules: continue
            if not p_rule_obj.is_ai_generated and not enable_standard_priority_rules: continue
            priority_rules.append(p_rule_obj)
        except Exception as err:
            logger.warning(f"Skipping invalid priority rule from database: {err}. Rule data: {pr}")

    overrides = []
    for o in overrides_data:
        try:
            overrides.append(ManualOverride(**o))
        except Exception as err:
            logger.warning(f"Skipping invalid override from database: {err}. Override data: {o}")

    for e in all_fetched_events:
        original_calendar_ids = list(e.calendar_ids)
        e.original_calendar_ids = original_calendar_ids
        
        # 1. Fetch Event Config
        config = None
        for src_id in getattr(e, 'source_event_ids', [e.id]):
            parts = src_id.split('::')
            google_id = parts[-1] if len(parts) > 1 else src_id
            config = storage.get_event_config(google_id)
            if config:
                e.app_config = config
                break
                
        # Fallback to recurring series config
        if not config and getattr(e, 'recurring_event_id', None):
            config = storage.get_event_config(e.recurring_event_id)
            if config:
                e.app_config = config

        if config and config.get('is_ignored'):
            continue
            
        if config and config.get('location_override'):
            e.location = config.get('location_override')
            
        if config and config.get('is_trip'):
            e.event_type = 'background_trip'
            
        if config and config.get('trip_id'):
            e.trip_id = config.get('trip_id')
            
        all_events_for_ui[e.id] = e

        # 2. Check Passengers (Config -> Rules -> Calendar/Hashtags)
        matched_passengers = []
        is_passenger = False

        driver_calendar_ids = [c for d in drivers for c in d.calendar_ids]
        is_driver_only = (
            all(c in driver_calendar_ids for c in original_calendar_ids) and 
            len(original_calendar_ids) > 0 and 
            not any(c in calendar_ids for c in original_calendar_ids)
        )
        
        if config and config.get('passenger_ids'):
            is_passenger = True
            config_pax_ids = [str(x) for x in config.get('passenger_ids', [])]
            matched_passengers = [p for p in passengers if str(p.id) in config_pax_ids]
        else:
            # Check Rules FIRST
            rule_matched = False
            for rule in rules:
                # Driver rules (e.g. unavailable, priority) should NOT convert an event into a passenger route!
                if getattr(rule, 'driver_id', None) is not None:
                    continue
                    
                if matcher.does_event_match_rule(e, rule, passengers):
                    matched_pax = [p for p in passengers if str(p.id) in rule.passenger_ids]
                    for p in matched_pax:
                        if p not in matched_passengers:
                            matched_passengers.append(p)
                    is_passenger = True
                    rule_matched = True
            
            # If no rule matched, fallback to hashtags and calendar_ids
            if not rule_matched:
                is_passenger = any(c in calendar_ids for c in original_calendar_ids)
                
                for p in passengers:
                    if any(c in p.calendar_ids for c in original_calendar_ids):
                        is_passenger = True
                        if p not in matched_passengers:
                            matched_passengers.append(p)
                    elif p.hashtags:
                        for tag in p.hashtags:
                            if fuzzy_has_hashtag(e.title, tag) or fuzzy_has_hashtag(e.description, tag):
                                is_passenger = True
                                if p not in matched_passengers:
                                    matched_passengers.append(p)
                                break

        if matched_passengers:
            e.calendar_ids = [str(p.id) for p in matched_passengers]

        # 3. Check Drivers
        driver_matched = False
        if config and config.get('driver_ids') is not None:
            driver_matched = True
            config_driver_ids = [str(x) for x in config.get('driver_ids', [])]
            for d in drivers:
                if str(d.id) in config_driver_ids:
                    driver_events_map[d.id].append(e)
                    driver_events_ids[d.id].append(e.id)
        else:
            for d in drivers:
                if any(c in d.calendar_ids for c in original_calendar_ids):
                    driver_matched = True
                    driver_events_map[d.id].append(e)
                    driver_events_ids[d.id].append(e.id)
                    continue
                for tag in d.hashtags:
                    if fuzzy_has_hashtag(e.title, tag) or fuzzy_has_hashtag(e.description, tag):
                        driver_matched = True
                        driver_events_map[d.id].append(e)
                        driver_events_ids[d.id].append(e.id)
                        break

        # 4. Triage Logic
        # Every event we haven't seen before (no config) goes to the inbox.
        # Driver-only events bypass the inbox to avoid clutter.
        if not config and not is_driver_only:
            e.needs_triage = True
                
        # 5. Append to events list if it's a passenger event AND has a location
        # (needs_triage events still go to the dashboard but are stripped out of solver below)
        if is_passenger:
            events.append(e)

    # Unroll events for passenger-specific times
    unrolled_events = []
    from collections import defaultdict
    for e in events:
        if not e.location or not e.location.strip():
            unrolled_events.append(e)
            continue
            
        config = e.app_config or {}
        pax_times = config.get('passenger_times', {})
        
        if pax_times:
            groups = defaultdict(list)
            for p_id in e.calendar_ids:
                times = pax_times.get(str(p_id))
                if times and (times.get('start') or times.get('end')):
                    groups[(times.get('start'), times.get('end'))].append(str(p_id))
                else:
                    groups[(None, None)].append(str(p_id))
            
            if len(groups) == 1 and (None, None) in groups:
                unrolled_events.append(e)
            else:
                idx = 0
                for time_tuple, p_ids in groups.items():
                    e_unrolled = e.model_copy() if hasattr(e, 'model_copy') else e.copy()
                    e_unrolled.id = f"{e.id}_unrolled_{idx}"
                    e_unrolled.original_event_id = getattr(e, 'original_event_id', None) or e.id
                    e_unrolled.calendar_ids = p_ids
                    
                    start_str, end_str = time_tuple
                    if start_str:
                        h, m = map(int, start_str.split(':'))
                        e_unrolled.start = e.start.replace(hour=h, minute=m, second=0, microsecond=0)
                    if end_str:
                        h, m = map(int, end_str.split(':'))
                        e_unrolled.end = e.end.replace(hour=h, minute=m, second=0, microsecond=0)
                    
                    unrolled_events.append(e_unrolled)
                    all_events_for_ui[e_unrolled.id] = e_unrolled
                    idx += 1
        else:
            unrolled_events.append(e)
            
    events = unrolled_events
    
    trip_metadata = []
    for e in all_events_for_ui.values():
        if getattr(e, 'event_type', '') == 'background_trip':
            applicable_entities = set()
            
            # Use triaged passenger assignments
            if hasattr(e, 'calendar_ids') and e.calendar_ids:
                for cid in e.calendar_ids:
                    applicable_entities.add(f"passenger_{cid}")
                    
            # Use triaged driver assignments
            for d_id, d_evs in driver_events_map.items():
                if any(de.id == e.id for de in d_evs):
                    applicable_entities.add(f"driver_{d_id}")
                    
            if not applicable_entities:
                applicable_entities.add('global')
                
            trip_start = e.start
            trip_end = e.end
            
            # Buffer trip with travel time
            if getattr(e, 'location', None):
                try:
                    tt = maps.get_travel_time_minutes(maps.get_home_location(), e.location)
                    # If tt is exactly the 15 min fallback, but they are in different states, it's likely an API failure for a long trip.
                    # A robust check: if API fails, tt=15. But we want a safe buffer.
                    # We will just apply it. The distance_cache usually prevents this.
                    trip_start -= timedelta(minutes=tt)
                    trip_end += timedelta(minutes=tt)
                except Exception as ex:
                    logger.warning(f"Failed to pad trip travel time: {ex}")
                    
            trip_metadata.append({
                "id": e.id,
                "start": trip_start,
                "end": trip_end,
                "location": e.location,
                "entities": applicable_entities,
                "all_day": e.all_day
            })
            
    for tm in trip_metadata:
        meta = storage.get_trip_metadata(tm['id'])
        if not meta or not meta.get('pois'):
            continue
            
        # If computing live schedule, reset all POIs
        if not draft and not start_date_str and not end_date_str:
            changed = False
            for poi in meta['pois']:
                if poi.get('is_scheduled'):
                    poi['is_scheduled'] = False
                    poi['scheduled_start'] = None
                    poi['scheduled_end'] = None
                    changed = True
            if changed:
                storage.set_trip_metadata(tm['id'], meta)
                
        for poi in meta['pois']:
            if poi.get('is_scheduled') and (not draft and not start_date_str and not end_date_str):
                continue
                
            starts_on_ts = tm['start'].timestamp()
            window_days = (tm['end'].date() - tm['start'].date()).days + 1
            
            errands.append({
                'id': f"{tm['id']}_poi_{poi['id']}",
                'doc_id': -1,
                'title': poi['name'],
                'location': poi['location'],
                'duration_mins': poi.get('duration_mins', 60),
                'priority': 2,
                'is_completed': False,
                'status': 'pending',
                'window_days': window_days,
                'starts_on': starts_on_ts,
                'tags': ['#trip_poi', tm['id']],
                'group_id': tm['id'],
                'trip_id': tm['id'],
                'poi_id': poi['id']
            })

    # Separate events with no location
    no_location_events = []
    events_to_solve = []
    
    # Filter out events where ALL passengers are on a background trip during the event time
    events_filtered = []
        
    for e in events:
        if getattr(e, 'event_type', '') == 'background_trip':
            events_filtered.append(e)
            continue
            
        if getattr(e, 'calendar_ids', []):
            kept_cids = []
            for cid in e.calendar_ids:
                pax_entity = f"passenger_{cid}"
                on_trip = False
                for tm in trip_metadata:
                    if pax_entity in tm['entities'] or 'global' in tm['entities']:
                        trip_start = tm['start']
                        trip_end = tm['end']
                        is_near_trip = False
                        if tm.get('location') and getattr(e, 'location', None):
                            # Ensure we don't drop events located NEAR the trip destination
                            try:
                                tt = maps.get_travel_time_minutes(e.location, tm['location'])
                                # Ignore the 15-minute fallback for `is_near_trip` if we are confident it failed.
                                # Actually, if it's 15, we accept it as near. 
                                if tt <= 180:
                                    is_near_trip = True
                            except:
                                pass
                                
                        if not is_near_trip and max(trip_start, e.start) < min(trip_end, e.end):
                            on_trip = True
                            break
                if not on_trip:
                    kept_cids.append(cid)
            
            if not kept_cids:
                all_events_for_ui.pop(e.id, None)
                continue
                
            e.calendar_ids = kept_cids
            
        events_filtered.append(e)

    events = events_filtered

    for e in events:
        if not e.location or not e.location.strip():
            no_location_events.append(e.id)
        else:
            duration_seconds = (e.end - e.start).total_seconds()
            has_stay_hashtag = fuzzy_has_hashtag(e.title, '#stay') or fuzzy_has_hashtag(getattr(e, 'description', ''), '#stay') or fuzzy_has_hashtag(e.title, '#wait') or fuzzy_has_hashtag(getattr(e, 'description', ''), '#wait')
            has_split_hashtag = fuzzy_has_hashtag(e.title, '#dropoff') or fuzzy_has_hashtag(getattr(e, 'description', ''), '#dropoff') or fuzzy_has_hashtag(e.title, '#pickup') or fuzzy_has_hashtag(getattr(e, 'description', ''), '#pickup')
            
            has_stay_rule = any(((r.constraint_type == 'attendance' and (r.attendance_action == 'stay' or r.attendance_action is None)) or r.constraint_type == 'no_split') and matcher.does_event_match_rule(e, r, passengers) for r in rules)
            has_split_rule = any(r.constraint_type == 'attendance' and r.attendance_action == 'dropoff_pickup' and matcher.does_event_match_rule(e, r, passengers) for r in rules)
            
            should_split = False
            if e.event_type != 'background_trip':
                if has_stay_hashtag or has_stay_rule:
                    should_split = False
                elif has_split_hashtag or has_split_rule:
                    should_split = True
                elif duration_seconds >= 7200:
                    should_split = True

            if getattr(e, 'needs_triage', False):
                continue
                
            if should_split:
                # Split into dropoff and pickup
                e_drop = e.model_copy() if hasattr(e, 'model_copy') else e.copy()
                e_drop.id = f"{e.id}_dropoff"
                e_drop.event_type = 'dropoff'
                e_drop.title = f"Dropoff: {e.title}"
                e_drop.end = e.start
                e_drop.original_start = e.start
                e_drop.original_end = e.end
                e_drop.original_event_id = e.id
                e_drop.needs_triage = False
                events_to_solve.append(e_drop)
                all_events_for_ui[e_drop.id] = e_drop
                
                e_pick = e.model_copy() if hasattr(e, 'model_copy') else e.copy()
                e_pick.id = f"{e.id}_pickup"
                e_pick.event_type = 'pickup'
                e_pick.title = f"Pickup: {e.title}"
                e_pick.start = e.end
                e_pick.original_start = e.start
                e_pick.original_end = e.end
                e_pick.original_event_id = e.id
                e_pick.end = e.end
                e_pick.needs_triage = False
                events_to_solve.append(e_pick)
                all_events_for_ui[e_pick.id] = e_pick
                
                # Note: We do NOT remove the original event from all_events_for_ui 
                # because the UI still needs it to render driver_events blocks (e.g. if a driver is attending the full camp).
            else:
                events_to_solve.append(e)
            
    old_cache = storage.get_cached_schedule()
    previous_assignments = old_cache.get("assignments", {})
            
    from collections import defaultdict
    import datetime

    # Pre-populate empty lists for the entire requested date range so empty days still get cached
    events_to_solve_by_date = defaultdict(list)
    fetched_by_date = defaultdict(list)
    
    now_tz = datetime.datetime.now().astimezone()
    range_s = datetime.datetime.fromisoformat(start_date_str.replace('Z', '+00:00')) if start_date_str else now_tz
    range_e = datetime.datetime.fromisoformat(end_date_str.replace('Z', '+00:00')) if end_date_str else now_tz + datetime.timedelta(days=days_to_fetch)
    
    curr_date = range_s
    while curr_date.date() <= range_e.date():
        d_str = curr_date.strftime("%Y-%m-%d")
        events_to_solve_by_date[d_str] = []
        fetched_by_date[d_str] = []
        curr_date += datetime.timedelta(days=1)

    # Group events to solve by local date
    for e in events_to_solve:
        curr = e.start.astimezone()
        end = e.end.astimezone()
        while curr.date() <= end.date():
            if curr.date() == end.date() and end.hour == 0 and end.minute == 0 and curr.date() != e.start.astimezone().date():
                break
            date_str = curr.strftime("%Y-%m-%d")
            if e not in events_to_solve_by_date[date_str]:
                events_to_solve_by_date[date_str].append(e)
            curr += datetime.timedelta(days=1)

    # Group all fetched events by local date (for hashing)
    for e in all_fetched_events:
        curr = e.start.astimezone()
        end = e.end.astimezone()
        
        # If it's a multi-day background trip, we will slice it into single-day chunks for the UI and solver
        if getattr(e, 'event_type', '') == 'background_trip':
            while curr.date() <= end.date():
                if curr.date() == end.date() and end.hour == 0 and end.minute == 0 and curr.date() != e.start.astimezone().date():
                    break
                date_str = curr.strftime("%Y-%m-%d")
                if date_str in fetched_by_date:
                    # Create a daily slice of the trip
                    daily_e = e.model_copy() if hasattr(e, 'model_copy') else e.copy()
                    daily_e.id = f"{e.id}_slice_{date_str}"
                    # Start is either the original start or midnight of this day
                    day_start = datetime.datetime.combine(curr.date(), datetime.time.min).astimezone(curr.tzinfo)
                    daily_e.start = max(e.start.astimezone(), day_start)
                    # End is either the original end or midnight of the next day
                    day_end = datetime.datetime.combine(curr.date() + datetime.timedelta(days=1), datetime.time.min).astimezone(curr.tzinfo)
                    daily_e.end = min(e.end.astimezone(), day_end)
                    if daily_e not in fetched_by_date[date_str]:
                        fetched_by_date[date_str].append(daily_e)
                    all_events_for_ui[daily_e.id] = daily_e
                curr += datetime.timedelta(days=1)
        else:
            while curr.date() <= end.date():
                if curr.date() == end.date() and end.hour == 0 and end.minute == 0 and curr.date() != e.start.astimezone().date():
                    break
                date_str = curr.strftime("%Y-%m-%d")
                if date_str in fetched_by_date:
                    if e not in fetched_by_date[date_str]:
                        fetched_by_date[date_str].append(e)
                curr += datetime.timedelta(days=1)

    old_cache = storage.get_cached_schedule()
    previous_assignments = old_cache.get("assignments", {})
    home_location = maps.get_home_location()
    calendar_metadata = None

    def compile_and_save_combined():
        nonlocal calendar_metadata
        combined_assignments = {}
        combined_unassigned = []
        combined_lateness_warnings = []
        combined_ghost_assignments = {}
        combined_ghost_drivers = []
        combined_events_to_solve = []
        combined_route_edges = {}
        combined_initial_edges = {}
        combined_final_edges = {}
        combined_true_unassigned = []
        combined_conflicts = []
        combined_scheduled_errands = []
        combined_ai_metadata = {}
        
        def merge_edges(target, source):
            if not source: return
            for d_id, edges in source.items():
                if d_id not in target:
                    target[d_id] = {}
                target[d_id].update(edges)

        for d_str in fetched_by_date.keys():
            daily_cache = storage.get_cached_daily_schedule(d_str)
            if daily_cache and 'schedule' in daily_cache:
                sched = daily_cache['schedule']
                combined_assignments.update(sched.get('assignments', {}))
                combined_unassigned.extend(sched.get('unassigned', []))
                combined_lateness_warnings.extend(sched.get('lateness_warnings', []))
                combined_ghost_assignments.update(sched.get('ghost_assignments', {}))
                
                existing_ghost_ids = {g['id'] for g in combined_ghost_drivers}
                for g in sched.get('ghost_drivers', []):
                    if g['id'] not in existing_ghost_ids:
                        combined_ghost_drivers.append(g)
                        existing_ghost_ids.add(g['id'])
                        
                combined_events_to_solve.extend(sched.get('events', []))
                merge_edges(combined_route_edges, sched.get('route_edges', {}))
                merge_edges(combined_initial_edges, sched.get('initial_edges', {}))
                merge_edges(combined_final_edges, sched.get('final_edges', {}))
                combined_true_unassigned.extend(sched.get('true_unassigned', []))
                combined_conflicts.extend(sched.get('conflicts', []))
                combined_scheduled_errands.extend(sched.get('scheduled_errands', []))
                
                if 'ai_status' in daily_cache:
                    combined_ai_metadata[d_str] = {
                        'ai_status': daily_cache.get('ai_status'),
                        'selected_index': daily_cache.get('selected_index'),
                        'llm_reasoning': daily_cache.get('llm_reasoning'),
                        'options': daily_cache.get('options', [])
                    }

        if not calendar_metadata:
            calendar_metadata = calendar.get_calendar_metadata(all_cals_to_fetch)
            # Inject passenger metadata
            PALETTE = ["#3B82F6", "#10B981", "#8B5CF6", "#EC4899", "#14B8A6", "#F97316", "#06B6D4", "#84CC16"]
            for p in passengers:
                color_index = sum(ord(c) for c in str(p.id)) % len(PALETTE)
                bg_color = PALETTE[color_index]
                fg_color = "#ffffff"
                if p.calendar_ids:
                    primary_cal = p.calendar_ids[0]
                    if primary_cal in calendar_metadata:
                        bg_color = calendar_metadata[primary_cal].get("backgroundColor", bg_color)
                        fg_color = calendar_metadata[primary_cal].get("foregroundColor", fg_color)
                calendar_metadata[str(p.id)] = {
                    "summary": p.name,
                    "backgroundColor": bg_color,
                    "foregroundColor": fg_color
                }

        if draft and not force_refresh:
            diagnostics = {}
        else:
            diagnostics = matcher.compute_diagnostics(
                combined_true_unassigned, list(all_events_for_ui.values()), drivers, driver_events_map, combined_assignments, overrides, rules, passengers=passengers
            )

        duplicate_groups = []
        schedule_one_rules = []
        schedule_all_rules = []
        for r in rules:
            if r.constraint_type == 'duplicate':
                action = getattr(r, 'duplicate_action', 'schedule_one')
                if action == 'schedule_all':
                    schedule_all_rules.append(r)
                else:
                    schedule_one_rules.append(r)

        from collections import defaultdict
        import datetime
        dup_groups = defaultdict(list)
        for e in all_events_for_ui.values():
            event_type = getattr(e, 'event_type', None)
            if event_type in ('pickup', 'dropoff', 'background_trip'):
                continue

            date_str = e.start.strftime('%Y-%m-%d')
            core_title = e.title.split(' - ')[0].split(':')[0].strip()
            cal_ids = tuple(sorted(e.calendar_ids))
            
            # Skip driver-only events
            if cal_ids and all(c in driver_calendar_ids for c in cal_ids):
                continue
                
            e_id = e.id
            e_title = e.title

            if any(matcher.does_event_match_rule(e, r, passengers) for r in schedule_one_rules):
                continue
            if any(matcher.does_event_match_rule(e, r, passengers) for r in schedule_all_rules):
                continue
                
            if len(core_title) > 3:
                key = (cal_ids, core_title)
                dup_groups[key].append((e_title, e_id, date_str))

        for key, evs in dup_groups.items():
            if len(evs) > 1:
                dates = sorted([datetime.datetime.strptime(e[2], '%Y-%m-%d').date() for e in evs])
                min_date = dates[0]
                max_date = dates[-1]
                delta = (max_date - min_date).days
                if delta == 0:
                    time_period = "daily"
                elif delta <= 7:
                    time_period = "weekly"
                elif delta <= 31:
                    time_period = "monthly"
                else:
                    time_period = "entire_period"
                    
                duplicate_groups.append({
                    "date": min_date.strftime('%Y-%m-%d'),
                    "keyword": key[1],
                    "time_period": time_period,
                    "original_titles": [e[0] for e in evs],
                    "event_ids": [e[1] for e in evs],
                    "passenger_ids": list(key[0])
                })

        # Calculate matched rules for each event
        matched_rules = {}
        for e in all_events_for_ui.values():
            m_rules = []
            for pr in priority_rules:
                if matcher.does_event_match_rule(e, pr, passengers):
                    pr_dict = pr.dict() if hasattr(pr, 'dict') else pr
                    pr_dict['_is_priority'] = True
                    m_rules.append(pr_dict)
            for r in rules:
                if matcher.does_event_match_rule(e, r, passengers):
                    r_dict = r.dict() if hasattr(r, 'dict') else r
                    r_dict['_is_priority'] = False
                    m_rules.append(r_dict)
            if m_rules:
                matched_rules[e.id] = m_rules

        data_payload = jsonable_encoder({
            "duplicate_groups": duplicate_groups,
            "events": list(all_events_for_ui.values()),
            "assignments": combined_assignments,
            "ghost_assignments": combined_ghost_assignments,
            "ghost_drivers": combined_ghost_drivers,
            "route_edges": combined_route_edges,
            "initial_edges": combined_initial_edges,
            "final_edges": combined_final_edges,
            "conflicts": combined_conflicts,
            "scheduled_errands": combined_scheduled_errands,
            "unassigned": combined_true_unassigned,
            "no_location": no_location_events,
            "overridden_events": matcher.get_effective_overridden_event_ids(list(all_events_for_ui.values()), overrides),
            "calendar_metadata": calendar_metadata,
            "lateness_warnings": combined_lateness_warnings,
            "passenger_calendar_ids": calendar_ids,
            "driver_events": driver_events_ids,
            "home_location": home_location or "",
            "diagnostics": diagnostics,
            "matched_rules": matched_rules,
            "passengers": passengers,
            "drivers": drivers,
            "solving_dates": schedule_coordinator.get_solving_dates(),
            "ai_metadata": combined_ai_metadata
        })

        if not start_date_str and not end_date_str:
            storage.set_cached_schedule(data_payload)
        else:
            storage.save_custom_schedule(start_date_str, end_date_str, data_payload, "")

        global LAST_UPDATE_TIME
        LAST_UPDATE_TIME = time.time()
        
        # --- Generate Pending Notifications ---
        if start_date_str is None and end_date_str is None:
            pending_notifications = []
            events_by_id = {e.id: e for e in all_events_for_ui.values()}
            import datetime
            now_ts = datetime.datetime.now().timestamp()
            
            existing_notifs = storage.get_pending_notifications()
            fired_notif_ids = {n["notif_id"] for n in existing_notifs if n.get("fired")}
            
            all_driver_ids = set()
            all_driver_ids.update(data_payload.get("initial_edges", {}).keys())
            all_driver_ids.update(data_payload.get("route_edges", {}).keys())
            all_driver_ids.update(data_payload.get("final_edges", {}).keys())
            
            for d_id in all_driver_ids:
                if d_id.startswith('ghost_'): continue
                
                for ev_id, edge in data_payload.get("initial_edges", {}).get(d_id, {}).items():
                    ev = events_by_id.get(ev_id)
                    if not ev: continue
                    pickup_wp = edge.get("pickup_waypoint")
                    buffer_before = edge.get("buffer_before_mins", 0)
                    ev_start_ts = datetime.datetime.fromisoformat(ev.start.isoformat()).timestamp()
                    
                    def add_init_notif(nid, ts, body, loc):
                        if now_ts <= ts + 600:
                            pending_notifications.append({
                                "notif_id": nid, "driver_id": d_id, "trigger_timestamp": ts,
                                "title": "Time to Leave!", "body": body, "location": loc, "fired": nid in fired_notif_ids
                            })

                    if pickup_wp:
                        pax_pickup_loc = pickup_wp.get("pickup_location", "")
                        driver_home_loc = edge.get("driver_home_location", "")
                        if pax_pickup_loc == driver_home_loc:
                            dep_time = ev_start_ts - (pickup_wp.get("from_global_home_mins", 0) + 5 + buffer_before) * 60
                            add_init_notif(f"init_{ev_id}", dep_time, f"Drive to {ev.location.split(',')[0]}", ev.location)
                        else:
                            dep1 = ev_start_ts - (pickup_wp.get("from_driver_home_mins", 0) + pickup_wp.get("from_global_home_mins", 0) + 5 + buffer_before) * 60
                            add_init_notif(f"init_{ev_id}_1", dep1, f"Pickup at {pax_pickup_loc.split(',')[0]}", pax_pickup_loc)
                            dep2 = ev_start_ts - (pickup_wp.get("from_global_home_mins", 0) + 5 + buffer_before) * 60
                            add_init_notif(f"init_{ev_id}_2", dep2, f"Drive to {ev.location.split(',')[0]}", ev.location)
                    else:
                        dep_time = ev_start_ts - (edge.get("travel_mins", 0) + 5 + buffer_before) * 60
                        add_init_notif(f"init_{ev_id}", dep_time, f"Drive to {ev.location.split(',')[0]}", ev.location)
                        
                for ev_id, edge in data_payload.get("route_edges", {}).get(d_id, {}).items():
                    ev = events_by_id.get(ev_id)
                    next_ev = events_by_id.get(edge.get("to_event", ""))
                    if not ev or not next_ev: continue
                    buffer_after = edge.get("buffer_after_mins", 0)
                    buffer_before = edge.get("buffer_before_mins", 0)
                    ev_end_ts = datetime.datetime.fromisoformat(ev.end.isoformat()).timestamp()
                    next_ev_start_ts = datetime.datetime.fromisoformat(next_ev.start.isoformat()).timestamp()
                    
                    home_wp = edge.get("home_waypoint")
                    pickup_wp = edge.get("pickup_waypoint")
                    
                    def add_notif(nid, ts, body, loc):
                        if now_ts <= ts + 600:
                            pending_notifications.append({
                                "notif_id": nid, "driver_id": d_id, "trigger_timestamp": ts,
                                "title": "Time to Leave!", "body": body, "location": loc, "fired": nid in fired_notif_ids
                            })

                    if home_wp and pickup_wp:
                        pax_pickup_loc = pickup_wp.get("pickup_location", "")
                        driver_home_loc = home_wp.get("driver_home_location", "")
                        dep1 = ev_end_ts + buffer_after * 60
                        add_notif(f"route_{ev_id}_{next_ev.id}_1", dep1, "Drive Home", settings.get("home_location", ""))
                        if pax_pickup_loc == driver_home_loc:
                            dep2 = max(dep1, next_ev_start_ts - (pickup_wp.get("from_pickup_mins", 0) + buffer_before + 5) * 60)
                            add_notif(f"route_{ev_id}_{next_ev.id}_2", dep2, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location)
                        else:
                            dep2 = max(dep1, next_ev_start_ts - (home_wp.get("from_home_mins", 0) + pickup_wp.get("from_pickup_mins", 0) + buffer_before + 5) * 60)
                            add_notif(f"route_{ev_id}_{next_ev.id}_2", dep2, f"Pickup at {pax_pickup_loc.split(',')[0]}", pax_pickup_loc)
                            dep3 = max(dep2, next_ev_start_ts - (pickup_wp.get("from_pickup_mins", 0) + buffer_before + 5) * 60)
                            add_notif(f"route_{ev_id}_{next_ev.id}_3", dep3, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location)
                    elif home_wp:
                        dep1 = ev_end_ts + buffer_after * 60
                        add_notif(f"route_{ev_id}_{next_ev.id}_1", dep1, "Drive Home", settings.get("home_location", ""))
                        dep2 = max(dep1, next_ev_start_ts - (home_wp.get("from_home_mins", 0) + buffer_before + 5) * 60)
                        add_notif(f"route_{ev_id}_{next_ev.id}_2", dep2, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location)
                    elif pickup_wp:
                        dep1 = ev_end_ts + buffer_after * 60
                        add_notif(f"route_{ev_id}_{next_ev.id}_1", dep1, f"Pickup at {pickup_wp.get('pickup_location', 'Location').split(',')[0]}", pickup_wp.get("pickup_location", ""))
                        dep2 = max(dep1, next_ev_start_ts - (pickup_wp.get("from_pickup_mins", 0) + buffer_before + 5) * 60)
                        add_notif(f"route_{ev_id}_{next_ev.id}_2", dep2, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location)
                    else:
                        dep_time = max(ev_end_ts + buffer_after * 60, next_ev_start_ts - (edge.get("travel_mins", 0) + buffer_before + 5) * 60)
                        add_notif(f"route_{ev_id}_{next_ev.id}", dep_time, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location)
                        
                for ev_id, edge in data_payload.get("final_edges", {}).get(d_id, {}).items():
                    ev = events_by_id.get(ev_id)
                    if not ev: continue
                    dep_time = datetime.datetime.fromisoformat(ev.end.isoformat()).timestamp() + edge.get("buffer_after_mins", 0) * 60
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
        return data_payload

    # Identify which dates actually need solving
    dates_needing_solve = []
    for date_str, daily_fetched in fetched_by_date.items():
        daily_hash = hash_events(daily_fetched)
        daily_cache = storage.get_cached_daily_schedule(date_str)
        if not (daily_cache and daily_cache.get('events_hash') == daily_hash and not force_refresh):
            dates_needing_solve.append(date_str)

    schedule_coordinator.start_solving(dates_needing_solve)

    # Save the initial combined cache immediately with the solving_dates list populated
    compile_and_save_combined()

    enable_ai_themes = settings.get("enable_ai_themes", True)
    all_themes = storage.get_all_themes()
    themes = []
    for t in all_themes:
        if not t.get('is_enabled', True): continue
        if t.get('is_ai_generated', False) and not enable_ai_themes: continue
        themes.append(t)
        
    default_theme = next((t for t in themes if "default" in (t.get('name') or '').lower() or "standard" in (t.get('name') or '').lower()), {})
    if not default_theme and themes:
        default_theme = themes[0]

    base_schedules = {}

    for date_str, daily_fetched in fetched_by_date.items():
        # Check abort at the start of each daily iteration
        check_abort_refresh()

        daily_hash = hash_events(daily_fetched)
        daily_events_to_solve = events_to_solve_by_date[date_str]

        # Check cache
        daily_cache = storage.get_cached_daily_schedule(date_str)
        if daily_cache and daily_cache.get('events_hash') == daily_hash and not force_refresh and not draft:
            sched = daily_cache.get('schedule', {})
            
            # Update previous_assignments so subsequent days know what was assigned!
            previous_assignments.update(sched.get("assignments", {}))
            
            base_schedules[date_str] = {
                "assignments": sched.get("assignments", {}),
                "unassigned": sched.get("unassigned", []),
                "lateness_warnings": sched.get("lateness_warnings", []),
                "ghost_assignments": sched.get("ghost_assignments", {}),
                "ghost_drivers": sched.get("ghost_drivers", []),
                "events": daily_events_to_solve,
                "true_unassigned": sched.get("true_unassigned", []),
                "conflicts": sched.get("conflicts", [])
            }
            continue

        # Else, solve for this day!
        daily_locations = set()
        if home_location:
            daily_locations.add(home_location)
        for p in passengers:
            if getattr(p, 'home_location', None):
                daily_locations.add(p.home_location)
        for d in drivers:
            if getattr(d, 'home_location', None):
                daily_locations.add(d.home_location)
        for e in daily_events_to_solve:
            if getattr(e, 'location', None):
                daily_locations.add(e.location)
        for trip in trip_metadata:
            if trip.get('location'):
                daily_locations.add(trip['location'])

        maps.prime_matrix_cache(list(daily_locations))

        # Check abort before running solver
        check_abort_refresh()


        if draft:
            assignments = {}
            if daily_cache and 'schedule' in daily_cache and 'assignments' in daily_cache['schedule']:
                assignments = dict(daily_cache['schedule']['assignments'])
            elif previous_assignments:
                assignments = dict(previous_assignments)
            
            for ov in overrides:
                if ov.driver_id == 'unassigned':
                    assignments.pop(ov.event_id, None)
                else:
                    assignments[ov.event_id] = ov.driver_id
                        
            unassigned = [e.id for e in daily_events_to_solve if e.id not in assignments]
            lateness_warnings = []
            
            # Draft mode is extremely lightweight, skip everything else
            ghost_assignments = {}
            ghost_drivers = []
            conflicts = []
            true_unassigned = unassigned
        else:
            assignments, unassigned, lateness_warnings = matcher.solve_schedule(
                daily_events_to_solve, drivers, rules, priority_rules, overrides=overrides, previous_assignments=previous_assignments, driver_events=driver_events_map, passengers=passengers, trip_metadata=trip_metadata, theme=default_theme
            )
            
            unassigned_events = [e for e in daily_events_to_solve if e.id in unassigned]
            assigned_events = [e for e in daily_events_to_solve if e.id in assignments]
            ghost_assignments, ghost_drivers = matcher.solve_ghost_routes(unassigned_events, assigned_events, rules, passengers)
            
            true_unassigned = [e.id for e in unassigned_events if e.id not in ghost_assignments]
            conflicts = matcher.compute_conflicts(assignments, ghost_assignments, daily_events_to_solve)

        base_schedules[date_str] = {
            "assignments": assignments,
            "unassigned": unassigned,
            "lateness_warnings": lateness_warnings,
            "ghost_assignments": ghost_assignments,
            "ghost_drivers": ghost_drivers,
            "events": daily_events_to_solve,
            "true_unassigned": true_unassigned,
            "conflicts": conflicts
        }
        
        # Update previous_assignments for the next day's solve!
        previous_assignments.update(assignments)

    # Pass 2: Global Errand Placement
    scheduled_errands_by_date = matcher.insert_errands_globally(base_schedules, errands, drivers, trip_metadata=trip_metadata) if not draft else {}

    # Pass 3: Route Edges and Caching
    from models.schemas import Event
    for date_str, daily_fetched in fetched_by_date.items():
        daily_hash = hash_events(daily_fetched)
        daily_events_to_solve = events_to_solve_by_date[date_str]
        base = base_schedules[date_str]

        scheduled_errands = scheduled_errands_by_date.get(date_str, [])
        errand_events = []
        for e_dict in scheduled_errands:
            try:
                errand_ev = Event(
                    id=e_dict['id'],
                    title=e_dict['title'],
                    start=datetime.datetime.fromisoformat(e_dict['start'].replace('Z', '+00:00')),
                    end=datetime.datetime.fromisoformat(e_dict['end'].replace('Z', '+00:00')),
                    location=e_dict['location'],
                    calendar_ids=[],
                    source_event_ids=[],
                    event_type="errand"
                )
                errand_events.append(errand_ev)
            except Exception as ex:
                logger.error(f"Failed to create errand Event for edges: {ex}")

        all_assignments = {**base['assignments'], **base['ghost_assignments']}
        for e_dict in scheduled_errands:
            all_assignments[e_dict['id']] = e_dict['driver']['id']
        all_events = daily_events_to_solve + errand_events
        
        if draft:
            route_edges, initial_edges, final_edges = {}, {}, {}
        else:
            route_edges, initial_edges, final_edges = matcher.compute_route_edges(
                all_assignments, all_events, drivers, home_location=home_location, 
                trip_metadata=trip_metadata, driver_attendances=driver_events_ids, 
                rules=rules, passengers=passengers
            )

        # Include all events for this day in the daily cache (not just passenger events)
        ui_events_for_day = []
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        for e in all_events_for_ui.values():
            curr = e.start.astimezone()
            end = e.end.astimezone()
            if curr.date() <= target_date <= end.date():
                if end.date() == target_date and end.hour == 0 and end.minute == 0 and curr.date() != end.date():
                    continue
                ui_events_for_day.append(e)

        daily_schedule = {
            "assignments": base['assignments'],
            "unassigned": base['unassigned'],
            "lateness_warnings": base['lateness_warnings'],
            "ghost_assignments": base['ghost_assignments'],
            "ghost_drivers": base['ghost_drivers'],
            "route_edges": route_edges,
            "initial_edges": initial_edges,
            "final_edges": final_edges,
            "events": [e.dict() if hasattr(e, 'dict') else e for e in ui_events_for_day],
            "true_unassigned": base['true_unassigned'],
            "conflicts": base['conflicts'],
            "scheduled_errands": scheduled_errands
        }
        

        # Save Trip POI scheduled state
        if not draft and not start_date_str and not end_date_str:
            for se in scheduled_errands:
                if '_poi_' in se['id']:
                    trip_id = se['id'].split('_poi_')[0]
                    poi_id = se['id'].split('_poi_')[1]
                    t_meta = storage.get_trip_metadata(trip_id)
                    if t_meta and 'pois' in t_meta:
                        for p in t_meta['pois']:
                            if p['id'] == poi_id:
                                p['is_scheduled'] = True
                                p['scheduled_start'] = se['start']
                                p['scheduled_end'] = se['end']
                        storage.set_trip_metadata(trip_id, t_meta)

        encoded_schedule = jsonable_encoder(daily_schedule)
        storage.save_cached_daily_schedule(date_str, encoded_schedule, daily_hash, ai_status='evaluating')

        # Background Evaluation (Disabled to save tokens/quota)
        other_themes = [t for t in themes if t.get('doc_id') != default_theme.get('doc_id')]
        provider = settings.get('llm_provider', '')
        if False:  # Disabled: AI multi-schedule evaluation disabled to save tokens/quota
            url = settings.get('llm_ollama_url', 'http://localhost:11434')
            api_key = settings.get('llm_gemini_api_key', '')
            model = settings.get('llm_gemini_model', 'gemini-3.5-flash') if provider == 'gemini' else settings.get('llm_ollama_model', 'qwen2.5:7b')
            philosophy = settings.get('family_philosophy', '')

            def bg_eval(d_str, d_hash, def_sched, def_theme, o_themes, d_evs, drvs, rls, prls, ovr, prev, d_map, paxs, meta, home_loc, p_events_ids, prov, ur, ak, mod, phil):
                options = [{
                    "theme_name": def_theme.get('name', 'Default'),
                    "schedule": def_sched,
                    "assignments_summary": ", ".join(f"{k}: {v}" for k,v in def_sched['assignments'].items()),
                    "unassigned_summary": ", ".join(def_sched['unassigned'])
                }]
                
                for t in o_themes:
                    a, u, lw = matcher.solve_schedule(d_evs, drvs, rls, prls, overrides=ovr, previous_assignments=prev, driver_events=d_map, passengers=paxs, trip_metadata=meta, theme=t)
                    ue = [e for e in d_evs if e.id in u]
                    ae = [e for e in d_evs if e.id in a]
                    ga, gd = matcher.solve_ghost_routes(ue, ae, rls, paxs)
                    all_a = {**a, **ga}
                    re, ie, fe = matcher.compute_route_edges(all_a, d_evs, drvs, home_location=home_loc, trip_metadata=meta, driver_attendances=p_events_ids, rules=rls, passengers=paxs)
                    tu = [e.id for e in ue if e.id not in ga]
                    c = matcher.compute_conflicts(a, ga, d_evs)
                    
                    ds = {
                        "assignments": a,
                        "unassigned": u,
                        "lateness_warnings": lw,
                        "ghost_assignments": ga,
                        "ghost_drivers": gd,
                        "route_edges": re,
                        "initial_edges": ie,
                        "final_edges": fe,
                        "events": [e.dict() if hasattr(e, 'dict') else e for e in d_evs],
                        "true_unassigned": tu,
                        "conflicts": c
                    }
                    options.append({
                        "theme_name": t.get('name', 'Alternative'),
                        "schedule": jsonable_encoder(ds),
                        "assignments_summary": ", ".join(f"{k}: {v}" for k,v in a.items()),
                        "unassigned_summary": ", ".join(u)
                    })
                
                from services.llm import evaluate_schedule_options
                import json
                feedback_docs = storage.get_recent_ai_feedback(limit=15)
                recent_feedback = [f.get('context', '') for f in feedback_docs if f.get('context')]
                
                sel_idx, reasoning = evaluate_schedule_options(prov, ur, ak, mod, phil, [d.dict() if hasattr(d, 'dict') else d for d in drvs], options, recent_feedback)
                
                ai_status = 'suggests_alternative' if sel_idx > 0 else 'approved_default'
                
                storage.save_cached_daily_schedule(d_str, options[sel_idx]["schedule"], d_hash, options=options, ai_status=ai_status, selected_index=sel_idx, llm_reasoning=reasoning)
                
                global LAST_UPDATE_TIME
                LAST_UPDATE_TIME = time.time()
                
            import threading
            threading.Thread(target=bg_eval, args=(date_str, daily_hash, encoded_schedule, default_theme, other_themes, daily_events_to_solve, drivers, rules, priority_rules, overrides, previous_assignments, driver_events_map, passengers, trip_metadata, home_location, driver_events_ids, provider, url, api_key, model, philosophy)).start()
        else:
            storage.save_cached_daily_schedule(date_str, encoded_schedule, daily_hash, ai_status=None)

        # Day finished, remove it from solving list and save combined!
        schedule_coordinator.finish_solving(date_str)
        compile_and_save_combined()

    # Final compile just in case, ensuring solving_dates is completely cleared for this run
    schedule_coordinator.clear_solving_dates()
    final_data = compile_and_save_combined()

    return final_data


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

@app.get("/api/debug_db")
def debug_db():
    return {
        "db_path": storage.DB_PATH,
        "themes_count": len(storage.themes_table.all()),
        "rules_count": len(storage.rules_table.all())
    }

@app.post("/api/drive_status")
def update_drive_status(status: DriveStatus):
    storage.mark_drive_status(status.leg_id, status.status)
    return {"status": "ok"}

custom_schedule_cache = {}

from fastapi import BackgroundTasks

last_bg_refresh = {}

@app.get("/api/schedule")
def get_schedule(background_tasks: BackgroundTasks, start_date: str = None, end_date: str = None, force_refresh: bool = False):
    try:
        completed = storage.get_completed_drives()
        in_progress = storage.get_in_progress_drives()
        
        # Check cache instantly
        if not force_refresh:
            if not start_date and not end_date:
                cached = storage.get_cached_schedule()
            else:
                cached_custom = storage.get_custom_schedule(start_date, end_date)
                cached = cached_custom.get('schedule') if cached_custom else None
                
                if not cached:
                    try:
                        from datetime import datetime, timedelta
                        s = datetime.fromisoformat(start_date.replace('Z', '+00:00')).date()
                        e = datetime.fromisoformat(end_date.replace('Z', '+00:00')).date()
                        
                        all_cached = True
                        combined_assignments = {}
                        combined_unassigned = []
                        combined_lateness_warnings = []
                        combined_ghost_assignments = {}
                        combined_ghost_drivers = []
                        combined_events_to_solve = []
                        combined_route_edges = {}
                        combined_initial_edges = {}
                        combined_final_edges = {}
                        combined_true_unassigned = []
                        combined_conflicts = []
                        combined_scheduled_errands = []
                        
                        def merge_edges(target, source):
                            if not source: return
                            for d_id, edges in source.items():
                                if d_id not in target:
                                    target[d_id] = {}
                                target[d_id].update(edges)
                                
                        current = s
                        while current <= e:
                            d_str = str(current)
                            daily_cache = storage.get_cached_daily_schedule(d_str)
                            if not daily_cache or 'schedule' not in daily_cache:
                                current += timedelta(days=1)
                                continue
                                
                            sched = daily_cache['schedule']
                            for d_id, evs in sched.get('assignments', {}).items():
                                if d_id not in combined_assignments:
                                    combined_assignments[d_id] = []
                                combined_assignments[d_id].extend(evs)
                            combined_unassigned.extend(sched.get('unassigned', []))
                            combined_lateness_warnings.extend(sched.get('lateness_warnings', []))
                            
                            for d_id, evs in sched.get('ghost_assignments', {}).items():
                                if d_id not in combined_ghost_assignments:
                                    combined_ghost_assignments[d_id] = []
                                combined_ghost_assignments[d_id].extend(evs)
                            
                            existing_ghost_ids = {g['id'] for g in combined_ghost_drivers}
                            for g in sched.get('ghost_drivers', []):
                                if g['id'] not in existing_ghost_ids:
                                    combined_ghost_drivers.append(g)
                                    existing_ghost_ids.add(g['id'])
                                    
                            combined_events_to_solve.extend(sched.get('events', []))
                            merge_edges(combined_route_edges, sched.get('route_edges', {}))
                            merge_edges(combined_initial_edges, sched.get('initial_edges', {}))
                            merge_edges(combined_final_edges, sched.get('final_edges', {}))
                            
                            combined_true_unassigned.extend(sched.get('true_unassigned', []))
                            combined_conflicts.extend(sched.get('conflicts', []))
                            
                            existing_errand_ids = {er['id'] for er in combined_scheduled_errands}
                            for er in sched.get('scheduled_errands', []):
                                if er['id'] not in existing_errand_ids:
                                    combined_scheduled_errands.append(er)
                                    existing_errand_ids.add(er['id'])
                                    
                            current += timedelta(days=1)
                            
                        if all_cached:
                            global_cache = storage.get_cached_schedule() or {}
                            cached = {
                                "assignments": combined_assignments,
                                "unassigned": combined_unassigned,
                                "lateness_warnings": combined_lateness_warnings,
                                "ghost_assignments": combined_ghost_assignments,
                                "ghost_drivers": combined_ghost_drivers,
                                "route_edges": combined_route_edges,
                                "initial_edges": combined_initial_edges,
                                "final_edges": combined_final_edges,
                                "events": combined_events_to_solve,
                                "true_unassigned": combined_true_unassigned,
                                "conflicts": combined_conflicts,
                                "scheduled_errands": combined_scheduled_errands,
                                "calendar_metadata": global_cache.get("calendar_metadata", {}),
                                "drivers": [d.dict() if hasattr(d, 'dict') else d for d in storage.get_all_drivers() if not d.get('is_disabled')],
                                "passengers": storage.get_all_passengers(),
                                "no_location": combined_events_to_solve and [e.get('id') for e in combined_events_to_solve if not e.get('location')] or []
                            }
                            storage.save_custom_schedule(start_date, end_date, cached)
                    except Exception as ex:
                        logger.error(f"Failed to combine daily caches: {ex}")
                        pass
                
            if cached:
                cached["completed_drives"] = completed
                cached["in_progress_drives"] = in_progress
                cached["solving_dates"] = schedule_coordinator.get_solving_dates()
                # Rate limit background refreshes to every 5 minutes per date range
                import time
                global last_bg_refresh
                cache_key = f"{start_date}_{end_date}"
                now = time.time()
                if now - last_bg_refresh.get(cache_key, 0) > 300:
                    last_bg_refresh[cache_key] = now
                    # Fire an async background refresh so Google Calendar latency (1-5s) doesn't block the UI
                    background_tasks.add_task(trigger_background_refresh, start_date, end_date, False)
                    
                if now - last_bg_refresh.get('full_30_days', 0) > 1800:
                    last_bg_refresh['full_30_days'] = now
                    background_tasks.add_task(trigger_background_refresh, None, None, False)
                return cached

        # Fetch fresh and block if no cache exists or forced
        try:
            if start_date and end_date:
                try:
                    from datetime import datetime
                    s = datetime.fromisoformat(start_date.replace('Z', '+00:00')).date()
                    e = datetime.fromisoformat(end_date.replace('Z', '+00:00')).date()
                    if (e - s).days > 7 and not force_refresh:
                        background_tasks.add_task(trigger_background_refresh, start_date, end_date, True)
                        return {"error": "Long date range requested. Schedule is calculating in the background. Please wait a moment."}
                except Exception:
                    pass

            res = refresh_schedule_logic(start_date, end_date, force_refresh=force_refresh)
            
            import time
            now = time.time()
            if now - last_bg_refresh.get('full_30_days', 0) > 1800:
                last_bg_refresh['full_30_days'] = now
                background_tasks.add_task(trigger_background_refresh, None, None, False)
                
            if "error" not in res:
                res["completed_drives"] = completed
                res["in_progress_drives"] = in_progress
                res["solving_dates"] = schedule_coordinator.get_solving_dates()
            return res
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc(), "error_debug": str(e)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/ha_sensors")
def get_ha_sensors(background_tasks: BackgroundTasks):
    try:
        cache = storage.get_cached_schedule()
        if not cache:
            cache = refresh_schedule_logic(None, None, True)
            
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
def force_refresh_schedule(background_tasks: BackgroundTasks, start_date: str = None, end_date: str = None, force: bool = True, draft: bool = False):
    refresh_schedule_logic(start_date, end_date, force_refresh=force, draft=draft)
    return {"status": "sync_finished"}




@app.get("/api/admin/clear_cache")
def clear_geocache():
    with storage.db_lock:
        storage.geocode_cache_table.truncate()
        storage.distance_cache_table.truncate()
        storage.daily_schedules_table.truncate()
        storage.custom_schedules_table.truncate()
    return {"status": "ok", "message": "Geocode, travel times, and schedule caches wiped successfully"}

@app.post("/api/test/set_mapbox_usage")
def test_set_mapbox_usage(endpoint: str, count: int):
    import datetime
    current_month = datetime.datetime.now().strftime("%Y-%m")
    
    with storage.db_lock:
        res = storage.api_usage_table.search((storage.Query().month == current_month) & (storage.Query().endpoint == endpoint))
        if res:
            storage.api_usage_table.update({'count': count}, (storage.Query().month == current_month) & (storage.Query().endpoint == endpoint))
        else:
            storage.api_usage_table.insert({'month': current_month, 'endpoint': endpoint, 'count': count})
            
    return {"status": "ok", "message": f"Set {endpoint} usage to {count} for {current_month}"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
