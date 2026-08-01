import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from fastapi import FastAPI, BackgroundTasks, Response, HTTPException, WebSocket, WebSocketDisconnect, Header
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
    member_id: Optional[str] = None  # hub identity; resolved from driver_id server-side when absent

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

from models.schemas import Driver, Rule, Settings, PriorityRule, ManualOverride, Passenger, FamilyMember, TelemetryEvent, Errand, ErrandRule
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

            # --- Evening "tomorrow" digest (once per day after the set time) ---
            try:
                settings = storage.get_settings() or {}
                if settings.get("tomorrow_digest_enabled", True):
                    now_dt = datetime.now()
                    hh, mm = [int(x) for x in str(settings.get("tomorrow_digest_time", "20:00")).split(":")[:2]]
                    today_str = now_dt.strftime('%Y-%m-%d')
                    if (now_dt.hour, now_dt.minute) >= (hh, mm) \
                            and storage.get_app_state("tomorrow_digest_last_sent") != today_str:
                        _send_tomorrow_digests(subs)
                        storage.set_app_state("tomorrow_digest_last_sent", today_str)
            except Exception as de:
                print(f"Tomorrow digest error: {de}")

        except Exception as e:
            print(f"Error in push loop: {e}")

        await asyncio.sleep(30)

def _send_tomorrow_digests(subs):
    """One evening push per subscribed driver listing tomorrow's assignments
    (events via the combined cache's assignments map, plus scheduled errands).
    Drivers with nothing tomorrow get no push."""
    import datetime as _dt
    from services import storage

    cache = storage.get_cached_schedule() or {}
    events = {e.get("id"): e for e in cache.get("events", [])}
    assignments = cache.get("assignments") or {}
    tomorrow = _dt.date.today() + _dt.timedelta(days=1)

    per_driver = {}
    for ev_id, d_id in assignments.items():
        if not d_id or str(d_id).startswith("ghost_"):
            continue
        ev = events.get(ev_id)
        if not ev:
            continue
        try:
            start = _dt.datetime.fromisoformat(ev["start"])
        except Exception:
            continue
        if start.date() != tomorrow:
            continue
        per_driver.setdefault(d_id, []).append((start, ev.get("title") or "Event"))

    for er in cache.get("scheduled_errands", []):
        d_id = (er.get("driver") or {}).get("id")
        if not d_id:
            continue
        try:
            start = _dt.datetime.fromisoformat(er["start_time"])
        except Exception:
            continue
        if start.date() != tomorrow:
            continue
        per_driver.setdefault(d_id, []).append((start, f"Errand: {er.get('title') or 'Errand'}"))

    subscribed = {s.get("driver_id") for s in subs}
    for d_id, items in per_driver.items():
        if d_id not in subscribed:
            continue
        items.sort(key=lambda x: x[0])
        lines = [f"{start.strftime('%I:%M %p').lstrip('0')} - {title}" for start, title in items[:6]]
        if len(items) > 6:
            lines.append(f"...and {len(items) - 6} more")
        n = len(items)
        send_push(d_id, subs, f"Tomorrow: {n} drive{'s' if n != 1 else ''}",
                  "\n".join(lines), f"digest_{tomorrow.isoformat()}", actions=[])

def send_push(d_id, subs, title, body, leg_id, location=None, actions=None):
    from pywebpush import webpush, WebPushException
    import json
    import urllib.parse

    navigate_url = None
    if actions is None:
        actions = [{"action": "complete", "title": "Mark Completed"}]
        if location:
            navigate_url = f"/app?navigate_dest={urllib.parse.quote(location)}&navigate_title={urllib.parse.quote(title)}&navigate_leg={leg_id}"
            actions.insert(0, {"action": "navigate", "title": "Navigate"})

    matched = 0
    for sub in subs:
        if sub.get("driver_id") == d_id:
            matched += 1
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
            except WebPushException as ex:
                code = getattr(getattr(ex, 'response', None), 'status_code', None)
                if code in (404, 410):
                    endpoint = (sub.get("subscription") or {}).get("endpoint")
                    print(f"Pruning dead push subscription for {d_id} (HTTP {code})")
                    if endpoint:
                        try:
                            from services import storage
                            storage.delete_push_subscription_by_endpoint(endpoint)
                        except Exception as prune_ex:
                            print(f"Failed to prune subscription: {prune_ex}")
                else:
                    print(f"Push failed for {d_id} (HTTP {code}): {repr(ex)}")
            except Exception as ex:
                print(f"Push failed for {d_id}: {repr(ex)}")
    if matched == 0:
        print(f"No push subscription for driver {d_id}; dropping push '{title}'")

import threading as _notif_threading
# Assignment changes buffered across a progressive re-solve run. The solver
# writes the combined cache once per solved day, so pushing per write would
# spam one notification per day — instead each write COLLECTS its diff here
# and the run's end (or a fallback timer) FLUSHES one push per driver.
_pending_assignment_changes = {}
_pending_changes_lock = _notif_threading.Lock()
_pending_flush_timer = None

def _fmt_change_event(ev):
    title = ev.get("title") or "Event"
    try:
        import datetime as _dt
        start = _dt.datetime.fromisoformat(ev["start"])
        return f"{title} ({start.strftime('%I:%M %p').lstrip('0')})"
    except Exception:
        return title

def _own_pwa_override(ev, d_id, overrides):
    ev_keys = {ev.get("id"), ev.get("original_event_id"), ev.get("recurring_event_id")}
    ev_keys.discard(None)
    for o in overrides:
        if getattr(o, "event_id", None) in ev_keys \
                and getattr(o, "driver_id", None) == d_id \
                and getattr(o, "source", None) == "pwa":
            return True
    return False

def _collect_assignment_changes(old_cache, new_payload, overrides):
    """Buffer assignment diffs from one cache write of a progressive re-solve.

    Only events present in BOTH snapshots count — calendar adds/removals are
    not assignment changes — and only upcoming events. Per event we keep the
    first old driver and the latest new driver, so churn within a run
    (A→B then B→A) nets out to nothing at flush time.
    """
    import datetime as _dt
    global _pending_flush_timer

    old_assign = old_cache.get("assignments") or {}
    new_assign = new_payload.get("assignments") or {}
    if not old_assign:
        return  # first-ever solve: everything would look "gained"

    old_event_ids = {e.get("id") for e in old_cache.get("events", [])}
    new_events = {e.get("id"): e for e in new_payload.get("events", [])}
    now = _dt.datetime.now()

    with _pending_changes_lock:
        for ev_id in set(old_assign) | set(new_assign):
            old_d = old_assign.get(ev_id)
            new_d = new_assign.get(ev_id)
            if old_d == new_d:
                continue
            ev = new_events.get(ev_id)
            if ev is None or ev_id not in old_event_ids:
                continue
            try:
                start = _dt.datetime.fromisoformat(ev["start"])
                if start.replace(tzinfo=None) < now:
                    continue
            except Exception:
                continue
            entry = _pending_assignment_changes.get(ev_id)
            if entry is None:
                entry = {"first_old": old_d, "pwa_claimer": None}
                _pending_assignment_changes[ev_id] = entry
            entry["last_new"] = new_d
            entry["ev"] = ev
            if new_d and _own_pwa_override(ev, new_d, overrides):
                entry["pwa_claimer"] = new_d

        # Fallback flush for any solve path that never reaches the
        # end-of-run flush in trigger_background_refresh.
        if _pending_assignment_changes:
            if _pending_flush_timer:
                _pending_flush_timer.cancel()
            _pending_flush_timer = _notif_threading.Timer(300, flush_assignment_notifications)
            _pending_flush_timer.daemon = True
            _pending_flush_timer.start()

def flush_assignment_notifications():
    """Send at most ONE Schedule Updated push per driver for a whole re-solve
    run: detailed +/- lines for TODAY's changes, a single summary line naming
    the affected dates for future days."""
    import datetime as _dt
    from services import storage
    global _pending_flush_timer

    with _pending_changes_lock:
        buffered = dict(_pending_assignment_changes)
        _pending_assignment_changes.clear()
        if _pending_flush_timer:
            _pending_flush_timer.cancel()
            _pending_flush_timer = None
    if not buffered:
        return

    today = _dt.date.today()
    changes = {}
    def _bucket(d_id):
        return changes.setdefault(d_id, {"today_gained": [], "today_lost": [], "future_dates": set()})

    for ev_id, entry in buffered.items():
        old_d = entry.get("first_old")
        new_d = entry.get("last_new")
        ev = entry.get("ev") or {}
        if old_d == new_d:
            continue  # churned back within the run — no net change
        try:
            start_date = _dt.datetime.fromisoformat(ev["start"]).date()
        except Exception:
            continue
        is_today = start_date == today
        if old_d and not str(old_d).startswith("ghost_"):
            if is_today:
                _bucket(old_d)["today_lost"].append(ev)
            else:
                _bucket(old_d)["future_dates"].add(start_date)
        if new_d and not str(new_d).startswith("ghost_") and entry.get("pwa_claimer") != new_d:
            if is_today:
                _bucket(new_d)["today_gained"].append(ev)
            else:
                _bucket(new_d)["future_dates"].add(start_date)

    if not changes:
        return

    subs = storage.get_push_subscriptions()
    for d_id, ch in changes.items():
        lines = [f"+ {_fmt_change_event(e)}" for e in ch["today_gained"]] \
              + [f"- {_fmt_change_event(e)}" for e in ch["today_lost"]]
        shown = lines[:5]
        if len(lines) > 5:
            shown.append(f"...and {len(lines) - 5} more today")

        fdates = sorted(ch["future_dates"])
        if fdates:
            dates_str = ", ".join(d.strftime('%a %m/%d') for d in fdates[:4])
            if len(fdates) > 4:
                dates_str += f" +{len(fdates) - 4} more"
            prefix = "Also changes on: " if lines else "Your upcoming schedule changed: "
            shown.append(prefix + dates_str)

        title = "Schedule Updated Today" if lines else "Schedule Updated"
        send_push(d_id, subs, title, "\n".join(shown),
                  f"sched_change_{int(time.time())}", actions=[])

        for e in ch["today_gained"]:
            storage.add_telemetry_event(TelemetryEvent(
                driver_id=d_id, event_id=e.get("id") or "",
                action="assigned", details=_fmt_change_event(e)).model_dump())
        for e in ch["today_lost"]:
            storage.add_telemetry_event(TelemetryEvent(
                driver_id=d_id, event_id=e.get("id") or "",
                action="removed", details=_fmt_change_event(e)).model_dump())
        if fdates:
            storage.add_telemetry_event(TelemetryEvent(
                driver_id=d_id, event_id="schedule", action="updated",
                details="Upcoming schedule changed: " + ", ".join(d.strftime('%a %m/%d') for d in fdates)).model_dump())

async def email_ingest_loop():
    """Poll the family intake mailbox every 10 minutes (services/email_ingest).
    New proposals push a review nudge to parents."""
    await asyncio.sleep(120)
    while True:
        try:
            from services import storage as _st, email_ingest
            settings = _st.get_settings() or {}
            if settings.get('ingest_email_enabled') and settings.get('ingest_email_user'):
                summary = await asyncio.to_thread(email_ingest.run_ingest)
                n = summary.get('proposed', 0)
                if n:
                    def _nudge_parents():
                        for m in _st.get_all_members():
                            if m.get('role') == 'parent':
                                # Deep link into the PWA Family tab (which
                                # hosts the approval queue for parents) — the
                                # dashboard /intake page is not reachable from
                                # a phone tap on the public origin.
                                _notify_member_lanes(
                                    m, 'New proposed events',
                                    f'📥 {n} new item{"s" if n != 1 else ""} extracted from family email — tap to review.',
                                    path='/app?view=family')
                    await asyncio.to_thread(_nudge_parents)
        except Exception as e:
            print(f"Email ingest loop error: {e}")
        await asyncio.sleep(600)

async def ics_sync_loop():
    """Hourly re-sync of subscribed ICS feeds (services/ics_sync.py). Hourly
    because same-day reschedules (rainouts) should land before pickup time.
    First pass waits a minute so startup isn't competing with the feed fetch."""
    await asyncio.sleep(60)
    while True:
        try:
            from services import ics_sync
            result = await asyncio.to_thread(ics_sync.sync_all_feeds)
            if result.get('changed'):
                await asyncio.to_thread(trigger_background_refresh)
        except Exception as e:
            print(f"ICS sync loop error: {e}")
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_schedule())
    push_task = asyncio.create_task(push_notification_loop())
    ics_task = asyncio.create_task(ics_sync_loop())
    ingest_task = asyncio.create_task(email_ingest_loop())

    from services.migrations import run_all_migrations
    migration_task = asyncio.create_task(run_all_migrations())

    yield
    task.cancel()
    push_task.cancel()
    ics_task.cancel()
    ingest_task.cancel()
    migration_task.cancel()

app = FastAPI(title="Family Driver Graph Scheduler", lifespan=lifespan)

@app.middleware("http")
async def slow_request_logger(request, call_next):
    """Log any request that takes >1s so slowness reports come with data."""
    import time as _time
    t0 = _time.monotonic()
    response = await call_next(request)
    dt = _time.monotonic() - t0
    if dt > 1.0:
        print(f"[SLOW REQUEST] {request.method} {request.url.path} took {dt:.2f}s")
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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
    # no-store like the dashboard: iOS caches installed-PWA start pages hard,
    # leaving phones on stale HTML for days after a release.
    response = templates.TemplateResponse(request=request, name="app.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/config")
def config(request: Request):
    return templates.TemplateResponse(request=request, name="config.html")

@app.get("/calendar", response_class=HTMLResponse)
def calendar_view(request: Request):
    return templates.TemplateResponse(request=request, name="calendar.html")

@app.get("/errands")
def errands(request: Request):
    return templates.TemplateResponse(request=request, name="errands.html")

@app.get("/chores")
def chores_page(request: Request):
    response = templates.TemplateResponse(request=request, name="chores.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/intake")
def intake_page(request: Request):
    response = templates.TemplateResponse(request=request, name="intake.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/routines")
def routines_page(request: Request):
    response = templates.TemplateResponse(request=request, name="routines.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/map")
def family_map_page(request: Request):
    response = templates.TemplateResponse(request=request, name="map.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

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

@app.post("/api/trip")
def create_trip_api(req: CreateTripRequest):
    import uuid
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    from services import maps
    from services.travel_api import get_live_flight_schedule
    
    draft_id = f"draft_trip_{uuid.uuid4().hex}"
    
    if req.start_date and req.end_date:
        # Exact dates provided
        def parse_date(d_str):
            if len(d_str) == 10:
                return datetime.strptime(d_str, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=9)
            return datetime.fromisoformat(d_str.replace('Z', '+00:00'))
            
        try:
            mock_start = parse_date(req.start_date)
            mock_end = parse_date(req.end_date)
        except Exception:
            mock_start = datetime.now(timezone.utc)
            mock_end = mock_start + timedelta(days=1)
    else:
        # Flexible dates: Calculate mock start
        base = datetime(2030, 1, 1, tzinfo=timezone.utc)
        day_of_week = req.start_day_of_week if req.start_day_of_week is not None else 0 # default Monday
        offset = (day_of_week - base.weekday()) % 7
        if offset < 0:
            offset += 7
            
        # 1. Determine Home Location and travel time
        home_loc = maps.get_home_location()
        dest_loc = req.location or "Unknown"
        travel_time_mins = maps.get_travel_time_minutes(home_loc, dest_loc) if home_loc else -1
        
        arrival_utc = None
        
        # 2. Determine Departure date string for flight searches
        mock_departure_base = base + timedelta(days=offset)
        dep_date_str = mock_departure_base.strftime("%Y-%m-%d")
        
        # 3. If driving is impossible (> 15 hrs approx) or failed (-1)
        if home_loc and (travel_time_mins == -1 or travel_time_mins >= 900):
            flight_schedule = get_live_flight_schedule(home_loc, dest_loc, dep_date_str)
            if flight_schedule and "arrival_time" in flight_schedule:
                try:
                    # arrival_time is '2030-01-05 14:40'
                    arr_dt = datetime.strptime(flight_schedule["arrival_time"], "%Y-%m-%d %H:%M")
                    # It's local to destination. Convert to UTC properly.
                    dest_tz_str = maps.get_timezone(dest_loc)
                    dest_tz = ZoneInfo(dest_tz_str)
                    arr_dt_local = arr_dt.replace(tzinfo=dest_tz)
                    # Add 1 hour buffer for airport overhead
                    arrival_utc = arr_dt_local.astimezone(timezone.utc) + timedelta(hours=1)
                except Exception as e:
                    print(f"Failed to parse flight schedule arrival time: {e}")
                    
        # 4. Fallback to driving or generic fallback
        if not arrival_utc:
            if home_loc and travel_time_mins > 0:
                try:
                    home_tz_str = maps.get_timezone(home_loc)
                    home_tz = ZoneInfo(home_tz_str)
                    # Assume 8 AM departure
                    leave_time = datetime(mock_departure_base.year, mock_departure_base.month, mock_departure_base.day, 8, 0, 0, tzinfo=home_tz)
                    arrival_utc = leave_time.astimezone(timezone.utc) + timedelta(minutes=travel_time_mins + 60)
                except Exception as e:
                    print(f"Failed to calculate driving arrival time: {e}")
                    
            if not arrival_utc:
                # Absolute fallback: 9 AM UTC
                arrival_utc = mock_departure_base + timedelta(hours=9)
                
        mock_start = arrival_utc
        duration = req.duration_nights or 1
        mock_end = mock_start + timedelta(days=duration)
        
    metadata = {
        "event_id": draft_id,
        "is_draft": True,
        "title": req.title,
        "location": req.location,
        "draft_start_day": req.start_day_of_week,
        "draft_duration_nights": req.duration_nights,
        "mock_start_date": mock_start.timestamp(),
        "mock_end_date": mock_end.timestamp(),
        "budget_min_usd": req.budget_min_usd,
        "budget_max_usd": req.budget_max_usd,
        "flight_preferences": req.flight_preferences,
        "attendees": req.attendees,
        "travelers": max(1, len(req.attendees)) if req.attendees else 1,
        "pois": [],
        "accommodations": [],
        "flights": [],
        "activities": []
    }
    storage.set_trip_metadata(draft_id, metadata)
    return {"success": True, "event_id": draft_id}

@app.get("/trip")
def trip_view(request: Request, event_id: str):
    import datetime
    current_month = datetime.datetime.now().strftime("%Y-%m")
    mapbox_key = maps.get_mapbox_api_key()
    enable_loads = maps.get_map_option('enable_mapbox_map_loads', True)
    limit = maps.get_map_option('mapbox_map_loads_limit', 45000)
    current_usage = storage.get_mapbox_usage(current_month, 'map_loads')
    allow_map_loads = enable_loads and (current_usage < limit)
    
    response = templates.TemplateResponse(request=request, name="trip.html", context={
        "event_id": event_id,
        "mapbox_key": mapbox_key,
        "allow_map_loads": allow_map_loads
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.get("/health")
def health_check():
    return {"status": "healthy"}

def _coerce_ts(v):
    """Normalize an activity start/end to a float unix timestamp.

    Activity starts arrive as unix floats (parse_dt, claimed_day_spans, most
    POI writers) but a legacy bug stored some POI scheduled_start values as ISO
    strings; the frontend needs numeric timestamps and Python can't sort mixed
    str/float, so coerce everything here. Unparseable/empty -> 0.0."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            pass
        try:
            from datetime import datetime as _dt, timezone as _tz
            s = v.replace('Z', '+00:00')
            if len(v) <= 10:
                return _dt.strptime(v, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp()
            return _dt.fromisoformat(s).timestamp()
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def _meal_from_iso(dt_iso: str):
    """Infer a meal_type from a timed event's local start (its ISO offset IS the
    local time). Restaurant reservations often have opaque names ('Chef Mickey',
    'Maria and Enzo') with no food keyword, but their time is a reliable signal.
    Gaps (mid-afternoon, late night) return None so a non-meal event isn't tagged."""
    import datetime as _dt
    if not dt_iso or len(dt_iso) <= 10:   # missing or all-day (no clock time)
        return None
    try:
        t = _dt.datetime.fromisoformat(dt_iso.replace('Z', '+00:00')).time()
    except ValueError:
        return None
    if _dt.time(6, 30) <= t < _dt.time(10, 45):
        return 'breakfast'
    if _dt.time(10, 45) <= t < _dt.time(15, 0):
        return 'lunch'
    if _dt.time(16, 0) <= t < _dt.time(21, 0):
        return 'dinner'
    return None


def _build_calendar_backed_poi(cal_event_id: str, service, trip_location: str = "") -> dict:
    """Turn a real Google Calendar event into a fixed, calendar-backed trip POI.
    Returns None if the event can't be fetched. The POI is is_scheduled at the
    event's real time so the scheduler locks around it and it renders on the
    itinerary exactly like a scheduled attraction."""
    if not service or "::" not in cal_event_id:
        return None
    cal_id, raw_id = cal_event_id.split("::", 1)
    try:
        g = service.events().get(calendarId=cal_id, eventId=raw_id).execute()
    except Exception as e:
        print(f"Could not fetch linked event {cal_event_id}: {e}")
        return None
    start_ts = _coerce_ts(g.get('start', {}).get('dateTime', g.get('start', {}).get('date')))
    end_ts = _coerce_ts(g.get('end', {}).get('dateTime', g.get('end', {}).get('date')))
    title = g.get('summary', 'Event')
    location = g.get('location', '') or title
    tl = title.lower()
    food_kw = ('lunch', 'dinner', 'breakfast', 'brunch', 'dining', 'restaurant',
               'cafe', 'café', 'table', 'reservation', 'bar', 'grill', 'bistro',
               'kitchen', 'eatery', 'tavern', 'buffet', 'steakhouse', 'ristorante', 'trattoria')
    # Time is the reliable meal signal when the name is opaque ('Chef Mickey').
    inferred_meal = _meal_from_iso(g.get('start', {}).get('dateTime'))
    is_food = any(k in tl for k in food_kw) or inferred_meal is not None
    category = 'food' if is_food else 'other'
    meal_type = inferred_meal if is_food else None
    dur = int((end_ts - start_ts) / 60) if end_ts > start_ts else 60

    # Enrich with the same Mapbox/Wikidata/OpenStreetMap data regular attractions
    # get (coords, hours, website, phone, cuisine, wikidata image). Best-effort and
    # done once at creation — a linked event is still useful without it.
    enrich = {}
    try:
        from services.trip_planner import enrich_poi_data
        enrich = enrich_poi_data(title, location, trip_location) or {}
    except Exception as e:
        print(f"Enrichment failed for linked event {cal_event_id}: {e}")

    import uuid as _uuid
    return {
        "id": _uuid.uuid4().hex,
        "name": title,
        # The event's own location (set in Google Calendar) is authoritative —
        # never let the fuzzy enrichment match overwrite it with a different
        # address. Enrichment still contributes the extras (image, hours, etc.).
        "location": location,
        "mapbox_id": enrich.get('mapbox_id'),
        "category": category,
        "meal_type": meal_type,
        "description": g.get('description', '') or '',
        "event_id": cal_event_id,
        "source_event_id": cal_event_id,
        "is_external_event": True,
        "is_scheduled": True,
        "scheduled_start": start_ts,
        "scheduled_end": end_ts,
        "duration_mins": max(15, dur),
        "priority": "must",   # a real booking is a fixed, must-honor anchor
        "lat": enrich.get('lat'),
        "lng": enrich.get('lng'),
        "wikidata_id": enrich.get('wikidata_id'),
        "opening_hours": enrich.get('opening_hours'),
        "website": enrich.get('website'),
        "phone_number": enrich.get('phone_number'),
        "cuisine": enrich.get('cuisine'),
        "internet_access": enrich.get('internet_access'),
        "image_url": enrich.get('image_url'),
        "link": enrich.get('link'),
    }


def _sync_linked_events_to_pois(metadata: dict, event_id: str, service) -> bool:
    """Reconcile externally-linked calendar events (Schedule-page event configs
    with trip_id == this trip) into calendar-backed POIs: create one when an
    event is newly linked, remove it when the event is unlinked. Committed POIs
    (events Chauffeur itself created from a POI) are left alone. Returns True if
    metadata changed. This is what makes a linked event show up as a POI, exactly
    as if it had been added through Add Attraction."""
    from services.storage import event_configs_table
    from tinydb import Query
    trip_cal_id = event_id.split("::", 1)[0] if "::" in event_id else "primary"

    linked = set()
    for conf in event_configs_table.search(Query().trip_id == event_id):
        gid = conf.get('google_id')
        if gid:
            linked.add(gid if "::" in gid else f"{trip_cal_id}::{gid}")

    pois = metadata.setdefault("pois", [])
    # An event Chauffeur committed from one of its own POIs is already represented;
    # never turn it into a second, external POI.
    committed_event_ids = {p.get("event_id") for p in pois if not p.get("is_external_event")}
    linked = {e for e in linked if e not in committed_event_ids}

    existing_by_source = {p.get("source_event_id"): p for p in pois if p.get("is_external_event")}
    changed = False

    trip_location = metadata.get("location", "") or ""
    for ev_id in linked:
        if ev_id in existing_by_source:
            continue
        poi = _build_calendar_backed_poi(ev_id, service, trip_location)
        if poi:
            pois.append(poi)
            changed = True

    for src, p in list(existing_by_source.items()):
        if src not in linked:   # user unlinked it on the Schedule page
            pois.remove(p)
            changed = True
            continue
        # A calendar-backed POI must always be scheduled at its real event time.
        # Heal it if its cal:: id was clobbered, if its scheduled state was wiped
        # (e.g. by the daily solver before it stopped touching trip POIs), or if it
        # was created before meal-time inference and is mis-categorized 'other'.
        # One fetch fixes all; once healed it stops re-fetching.
        needs_reanchor = (p.get("event_id") != src or not p.get("is_scheduled")
                          or not p.get("scheduled_start"))
        needs_category = p.get("category") != 'food'
        if (needs_reanchor or needs_category) and "::" in src and service:
            try:
                cal_id, raw_id = src.split("::", 1)
                g = service.events().get(calendarId=cal_id, eventId=raw_id).execute()
                if needs_reanchor:
                    p["event_id"] = src
                    p["is_scheduled"] = True
                    p["scheduled_start"] = _coerce_ts(g.get('start', {}).get('dateTime', g.get('start', {}).get('date')))
                    p["scheduled_end"] = _coerce_ts(g.get('end', {}).get('dateTime', g.get('end', {}).get('date')))
                    changed = True
                if needs_category:
                    mt = _meal_from_iso(g.get('start', {}).get('dateTime'))
                    if mt:   # a real reservation at a meal time -> a meal that reserves its block
                        p["category"] = 'food'
                        if not p.get("meal_type"):
                            p["meal_type"] = mt
                        changed = True
            except Exception as e:
                print(f"Could not heal calendar-backed POI {src}: {e}")

    # The legacy activities list is retired under the POI-centric model.
    if metadata.get("activities"):
        metadata["activities"] = []
        changed = True

    if changed:
        storage.set_trip_metadata(metadata.get("event_id", event_id), metadata)
    return changed


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
            # A location that never resolves would otherwise cost a geocode on EVERY
            # fetch of this trip — retry at most once per hour per process.
            import time as _time
            if not hasattr(get_trip_api, "_tz_checked"):
                get_trip_api._tz_checked = {}
            last = get_trip_api._tz_checked.get(event_id, 0)
            if _time.monotonic() - last > 3600:
                get_trip_api._tz_checked[event_id] = _time.monotonic()
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
                    background_url = f"api/unsplash/background?query={encoded_query}"

                from services.trip_scheduler import claimed_day_spans
                spans = claimed_day_spans(poi, tz_str)
                if spans:
                    # Multi-day anchor: one day-view card per claimed date
                    for i, n, day_start, day_end in spans:
                        activities_details.append({
                            # suffix keeps UI POI-matching (act.id.endsWith(poi.event_id)) working
                            "id": f"day{i+1}_{poi.get('event_id')}",
                            "title": f"{poi.get('name', '')} (Day {i+1} of {n})",
                            "location": poi.get("location", ""),
                            "description": poi.get("description", ""),
                            "start": day_start,
                            "end": day_end,
                            "background_url": background_url
                        })
                    continue

                activities_details.append({
                    "id": poi.get("event_id"),
                    "title": poi.get("name", ""),
                    "location": poi.get("location", ""),
                    "description": poi.get("description", ""),
                    "start": poi.get("scheduled_start", 0),
                    "end": poi.get("scheduled_end", 0),
                    "background_url": background_url
                })
        for a in activities_details:
            a["start"] = _coerce_ts(a.get("start"))
            a["end"] = _coerce_ts(a.get("end"))
        activities_details.sort(key=lambda x: x["start"])

        return {
            "metadata": metadata,
            "event": event_details,
            "activities": activities_details
        }
    if not metadata and "::" in event_id:
        cal_id, raw_event_id = event_id.split("::", 1)
        base_id = f"{cal_id}::{raw_event_id.split('_')[0]}"
        metadata = storage.get_trip_metadata(base_id)
    metadata = metadata or {"event_id": event_id, "pois": [], "accommodations": [], "flights": [], "activities": []}
    if "activities" not in metadata:
        metadata["activities"] = []
    if "accommodations" not in metadata:
        metadata["accommodations"] = []
    if "flights" not in metadata:
        metadata["flights"] = []
    
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
            
    # POI-centric model: events linked to this trip (Schedule-page event configs
    # with trip_id set) are reconciled into calendar-backed POIs — created on
    # link, removed on unlink — so they render and schedule exactly like any
    # attraction. The old separate "activities" list is retired here.
    _sync_linked_events_to_pois(metadata, event_id, service)
    activities_details = []

    # Self-heal scheduled POIs that never got a draft_poi_ event_id: the main
    # daily solver's write-back marks trip POIs is_scheduled with a scheduled_start
    # but historically left event_id empty, so they counted as "scheduled" in the
    # attractions list yet never appeared in the itinerary below (which keys off a
    # draft_poi_ id). Backfill the id so the two views agree.
    import uuid as _uuid
    _healed = False
    for poi in metadata.get("pois", []):
        # Skip calendar-backed POIs — their event_id is a real cal:: id we must keep.
        if poi.get("is_external_event") or _is_calendar_backed_poi(poi):
            continue
        if poi.get("is_scheduled") and poi.get("scheduled_start") and not (poi.get("event_id") or "").startswith("draft_poi_"):
            poi["event_id"] = f"draft_poi_{_uuid.uuid4().hex}"
            _healed = True
    if _healed:
        storage.set_trip_metadata(metadata.get("event_id", event_id), metadata)

    # Inject scheduled POIs (fuzzy draft_poi_ AND calendar-backed) into the itinerary.
    for poi in metadata.get("pois", []):
        ev = poi.get("event_id") or ""
        cal_backed = _is_calendar_backed_poi(poi)
        if not (poi.get("is_scheduled") and poi.get("scheduled_start") and (ev.startswith("draft_poi_") or cal_backed)):
            continue
        act_cal_id = event_id.split("::", 1)[0] if "::" in event_id else "primary"
        from services.trip_scheduler import claimed_day_spans
        spans = claimed_day_spans(poi, metadata.get("timeZone"))
        if spans:
            # Multi-day anchor: one day-view card per claimed date (possibly non-consecutive)
            for i, n, day_start, day_end in spans:
                activities_details.append({
                    # suffix keeps UI POI-matching (act.id.endsWith(poi.event_id)) working
                    "id": f"{act_cal_id}::day{i+1}_{ev}",
                    "title": f"{poi.get('name', '')} (Day {i+1} of {n})",
                    "location": poi.get("location", ""),
                    "description": poi.get("notes") or poi.get("description", ""),
                    "start": day_start,
                    "end": day_end,
                    "background_url": poi.get("image_url") or metadata.get("background_url"),
                    "poi_id": poi.get("id"),
                    "is_external": bool(poi.get("is_external_event"))
                })
            continue
        # A calendar-backed POI's event_id is already a full cal:: id; a fuzzy POI's
        # needs the trip calendar prefix so the UI's endsWith(event_id) match works.
        act_id = ev if cal_backed else f"{act_cal_id}::{ev}"
        # scheduled_start is normally a unix float, but a legacy writer stored
        # some as ISO strings — coerce before the +3600 arithmetic below.
        sched_start = _coerce_ts(poi.get("scheduled_start"))
        activities_details.append({
            "id": act_id,
            "title": poi.get("name", ""),
            "location": poi.get("location", ""),
            "description": poi.get("notes") or poi.get("description", ""),
            "start": sched_start,
            "end": _coerce_ts(poi.get("scheduled_end")) or (sched_start + 3600),
            "background_url": poi.get("image_url") or metadata.get("background_url"),
            "poi_id": poi.get("id"),
            "is_external": bool(poi.get("is_external_event"))
            })

    # Sort activities by start time (normalize any heterogeneous types first)
    for a in activities_details:
        a["start"] = _coerce_ts(a.get("start"))
        a["end"] = _coerce_ts(a.get("end"))
    activities_details.sort(key=lambda x: x["start"])
            
    return {
        "event": event_details,
        "metadata": metadata,
        "activities": activities_details
    }

@app.post("/api/trip/{event_id}/suggest_dates")
def suggest_dates_api(event_id: str):
    from models.schemas import TripMetadata
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"error": "Trip not found."}
    trip = TripMetadata(**meta)
    
    from services.trip_planner import suggest_trip_dates
    err, suggestion = suggest_trip_dates(trip)
    if err:
        return {"error": err}
    return {"suggestion": suggestion}

@app.post("/api/trip/{event_id}/schedule")
def schedule_trip_api(event_id: str, payload: dict):
    from models.schemas import TripMetadata
    from services.calendar import get_calendar_service
    import datetime
    
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"error": "Trip not found."}
        
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    cal_id = payload.get("calendar_id", "primary")
    
    if meta.get("is_draft") and (not start_date or not end_date):
        return {"error": "start_date and end_date are required."}
        
    # Create the main trip event in Google Calendar if it's a draft
    service = get_calendar_service()
    if meta.get("is_draft"):
        event_body = {
            "summary": meta.get("title", "New Trip"),
            "description": "#trip\n" + (meta.get("notes") or ""),
            "start": {"date": start_date},
            "end": {"date": end_date}
        }
        if meta.get("location"):
            event_body["location"] = meta.get("location")
            
        try:
            created = service.events().insert(calendarId=cal_id, body=event_body).execute()
            new_event_id = f"{cal_id}::{created['id']}"
            meta["event_id"] = new_event_id
            meta["is_draft"] = False
        except Exception as e:
            return {"error": f"Failed to create Google Calendar event: {e}"}
    else:
        new_event_id = meta.get("event_id")
        
    # Schedule all previously drafted POIs to real calendar events
    from services.calendar import create_event as cal_create_event
    for poi in meta.get("pois", []):
        if poi.get("is_scheduled") and poi.get("event_id", "").startswith("draft_poi_"):
            try:
                best_start_iso = datetime.datetime.fromtimestamp(poi["scheduled_start"], tz=datetime.timezone.utc).isoformat()
                best_end_iso = datetime.datetime.fromtimestamp(poi["scheduled_end"], tz=datetime.timezone.utc).isoformat()
                
                desc = poi.get("description") or ""
                if poi.get("notes"):
                    desc += f"\n\nNotes: {poi.get('notes')}"
                    
                poi_cal_id = cal_create_event(
                    calendar_id=cal_id,
                    title=poi.get("name", "POI"),
                    start=best_start_iso,
                    end=best_end_iso,
                    location=poi.get("location", ""),
                    description=desc,
                    trip_id=new_event_id,
                    poi_id=poi.get("id"),
                    event_type="trip_background" if poi.get("is_background") else "standard"
                )
                if poi_cal_id:
                    poi["event_id"] = f"{cal_id}::{poi_cal_id}"
            except Exception as e:
                print(f"Failed to create calendar event for POI {poi.get('id')}: {e}")
            
    storage.set_trip_metadata(new_event_id, meta)
    
    # We must delete the old draft key if it was a draft
    if event_id != new_event_id:
        storage.delete_trip_metadata(event_id)
        
    return {"status": "success", "event_id": new_event_id}

@app.post("/api/trip/{event_id}/activity")
def add_activity_api(event_id: str, payload: dict):
    """Link an existing calendar event to the trip, or create a new one and link
    it. POI-centric: linking sets the event's config trip_id so the get_trip_api
    sync turns it into a calendar-backed POI (the old meta["activities"] list is
    retired). payload = {"activity_id": "cal::event"} to link existing, or
    {"title","location","start","end","calendar_id"} to create-then-link."""
    from services.calendar import get_calendar_service
    try:
        service = get_calendar_service()
    except Exception:
        service = None

    act_id = payload.get("activity_id")
    if not act_id and "title" in payload:
        if not service:
            return {"error": "Calendar service unavailable"}
        cal_id = payload.get("calendar_id") or (event_id.split("::", 1)[0] if "::" in event_id else "primary")
        event_body = {
            "summary": payload["title"],
            "location": payload.get("location", ""),
            "start": {"dateTime": payload["start"]},
            "end": {"dateTime": payload["end"]}
        }
        res = service.events().insert(calendarId=cal_id, body=event_body).execute()
        act_id = f"{cal_id}::{res['id']}"

    if not act_id:
        return {"error": "activity_id or title required"}

    # Link via the event config's trip_id — the single source the POI sync reads.
    raw_id = act_id.split("::", 1)[1] if "::" in act_id else act_id
    conf = dict(storage.get_event_config(raw_id) or {"google_id": raw_id})
    conf["trip_id"] = event_id
    storage.set_event_config(raw_id, conf)

    # Reconcile now so the calendar-backed POI shows up immediately.
    meta = storage.get_trip_metadata(event_id)
    if meta is not None:
        _sync_linked_events_to_pois(meta, event_id, service)

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
        # Never delete an externally-authored event through Chauffeur.
        if _is_chauffeur_calendar_event(activity_id):
            cal_id, raw_id = activity_id.split("::", 1)
            try:
                from services.calendar import get_calendar_service
                service = get_calendar_service()
                service.events().delete(calendarId=cal_id, eventId=raw_id).execute()
            except Exception as e:
                print(f"Error deleting activity from calendar: {e}")
        else:
            print(f"Refusing to delete non-Chauffeur event {activity_id}")

    return {"status": "ok"}

@app.post("/api/trip/{event_id}/activities/delete_bulk")
def delete_activities_bulk_api(event_id: str, payload: dict):
    meta = storage.get_trip_metadata(event_id)
    if not meta: return {"status": "ok"}
    
    activity_ids = payload.get("activity_ids", [])
    delete_from_calendar = payload.get("delete_from_calendar", False)
    
    changed = False
    for activity_id in activity_ids:
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

    if delete_from_calendar:
        try:
            from services.calendar import get_calendar_service
            service = get_calendar_service()
            for activity_id in activity_ids:
                if "::" in activity_id:
                    cal_id, raw_id = activity_id.split("::", 1)
                    try:
                        service.events().delete(calendarId=cal_id, eventId=raw_id).execute()
                    except Exception as e:
                        print(f"Error deleting activity {activity_id} from calendar: {e}")
        except Exception as e:
            pass

    return {"status": "ok"}

def _is_chauffeur_calendar_event(cal_event_id: str) -> bool:
    """True only if Chauffeur created this Google event (it carries our poi_id
    stamp). Externally-authored events linked into a trip must NEVER be deletable
    through Chauffeur — deleting the itinerary must not destroy, e.g., a family
    member's reservation."""
    if not cal_event_id or "::" not in cal_event_id:
        return False
    try:
        from services.calendar import get_calendar_service
        cal_id, raw_id = cal_event_id.split("::", 1)
        g = get_calendar_service().events().get(calendarId=cal_id, eventId=raw_id).execute()
        props = (g.get("extendedProperties", {}) or {}).get("private", {}) or {}
        return bool(props.get("poi_id") or props.get("trip_id"))
    except Exception as e:
        # Unknown provenance -> refuse to delete. Safety beats convenience.
        print(f"Provenance check failed for {cal_event_id}, will NOT delete: {e}")
        return False


@app.delete("/api/trip/{event_id}/activities")
def clear_itinerary_api(event_id: str, delete_from_calendar: bool = False):
    meta = storage.get_trip_metadata(event_id)
    if not meta: return {"status": "ok"}

    # Capture the calendar events THIS trip created (committed POIs carry a cal::
    # event_id in our own pois list) BEFORE we reset POI state below. Externally
    # linked events live in meta["activities"] and are only ever unlinked, never
    # deleted — so they are deliberately excluded from the delete set.
    committed_poi_events = [p.get("event_id") for p in meta.get("pois", [])
                            if "::" in (p.get("event_id") or "")
                            and not (p.get("event_id") or "").startswith("draft_poi_")]

    changed = False
    if "activities" in meta and meta["activities"]:
        meta["activities"] = []   # unlink external events; the events stay in Google
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
        # Delete only events Chauffeur created, and double-check provenance on the
        # Google event itself before each delete.
        for act_id in committed_poi_events:
            if _is_chauffeur_calendar_event(act_id):
                try:
                    from services.calendar import get_calendar_service
                    cal_id, raw_id = act_id.split("::", 1)
                    get_calendar_service().events().delete(calendarId=cal_id, eventId=raw_id).execute()
                except Exception as e:
                    print(f"Error deleting {act_id} from calendar: {e}")

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
        duration = payload.get("draft_duration_nights", 1)
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


@app.post("/api/trip/{event_id}/generate_plan")
def generate_trip_plan_api(event_id: str, payload: dict):
    user_prompt = payload.get("prompt", "")
    duration_nights = payload.get("duration_nights", 1)
    
    if not user_prompt:
        return {"error": "Prompt is required"}
        
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"error": "Trip not found"}
        
    from datetime import datetime, timezone
    from models.schemas import TripPlan
    
    trip_obj = TripPlan(
        id=payload.get("event_id"),
        mock_start_date=datetime.fromtimestamp(payload.get("mock_start_date"), tz=timezone.utc),
        mock_end_date=datetime.fromtimestamp(payload.get("mock_end_date"), tz=timezone.utc),
        duration_days=duration_nights,
        location=payload.get("location"),
        timeZone=payload.get("timeZone", "UTC"),
        budget_min_usd=payload.get("budget_min_usd"),
        budget_max_usd=payload.get("budget_max_usd"),
        flight_preferences=payload.get("flight_preferences"),
        attendees=payload.get("attendees", []),
        travelers=payload.get("travelers", 1)
    )
    
    from services.trip_planner import generate_trip_plan
    warning, pois, accs, flights = generate_trip_plan(trip_obj, user_prompt, duration_nights)
    
    # Save back to trip metadata
    if 'pois' not in meta:
        meta['pois'] = []
    if 'accommodations' not in meta:
        meta['accommodations'] = []
    if 'flights' not in meta:
        meta['flights'] = []
        
    # Deduplicate POIs by name
    existing_poi_names = {p.get('name', '').lower() for p in meta['pois']}
    for poi in pois:
        if poi.name.lower() not in existing_poi_names:
            poi_dict = poi.model_dump() if hasattr(poi, 'model_dump') else poi.dict()
            meta['pois'].append(poi_dict)
            existing_poi_names.add(poi.name.lower())
            
    # Deduplicate accommodations by name
    existing_acc_names = {a.get('name', '').lower() for a in meta['accommodations']}
    for acc in accs:
        if acc.name.lower() not in existing_acc_names:
            acc_dict = acc.model_dump() if hasattr(acc, 'model_dump') else acc.dict()
            meta['accommodations'].append(acc_dict)
            existing_acc_names.add(acc.name.lower())
            
    # Deduplicate flights by origin-destination-airline
    existing_flight_keys = {f"{f.get('origin')}-{f.get('destination')}-{f.get('airline')}" for f in meta['flights']}
    for flight in flights:
        key = f"{flight.origin}-{flight.destination}-{flight.airline}"
        if key not in existing_flight_keys:
            flight_dict = flight.model_dump() if hasattr(flight, 'model_dump') else flight.dict()
            meta['flights'].append(flight_dict)
            existing_flight_keys.add(key)
        
    storage.set_trip_metadata(event_id, meta)
    
    return {"budget_warning": warning, "pois": meta['pois'], "accommodations": meta['accommodations'], "flights": meta['flights']}

@app.post("/api/trip/{event_id}/generate_accommodations")
def generate_trip_accommodations_api(event_id: str, payload: dict):
    try:
        user_prompt = payload.get("prompt")
        if not user_prompt:
            return {"error": "Prompt is required"}
            
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
            
        from models.schemas import TripMetadata
        trip_obj = TripMetadata(**meta)
        
        from services.trip_planner import generate_trip_accommodations
        warning, accs = generate_trip_accommodations(trip_obj, user_prompt)
        
        # Save back to trip metadata
        if 'accommodations' not in meta:
            meta['accommodations'] = []
        
        existing_acc_names = {a.get('name', '').lower() for a in meta['accommodations']}
        for acc in accs:
            if acc.name.lower() not in existing_acc_names:
                acc_dict = acc.model_dump() if hasattr(acc, 'model_dump') else acc.dict()
                meta['accommodations'].append(acc_dict)
                existing_acc_names.add(acc.name.lower())
            
        storage.set_trip_metadata(event_id, meta)
        
        return {"budget_warning": warning, "accommodations": meta['accommodations']}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.post("/api/trip/{event_id}/live_pricing")
def live_pricing_api(event_id: str):
    from services.travel_api import get_live_flight_price, get_live_hotel_price, QuotaExceededError
    
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"error": "Trip not found"}
        
    travelers = meta.get("travelers", 1)
        
    updated = False
    quota_exceeded = False
    
    try:
        # Process Flights
        for flight in meta.get("flights", []):
            if not flight.get("is_live_price") and flight.get("origin") and flight.get("destination") and flight.get("departure_time"):
                try:
                    departure_date = flight["departure_time"].split("T")[0]
                    price = get_live_flight_price(flight["origin"], flight["destination"], departure_date, travelers)
                    if price is not None:
                        flight["estimated_price_usd"] = price
                        flight["is_live_price"] = True
                        updated = True
                except QuotaExceededError:
                    quota_exceeded = True
                    break
                except Exception as e:
                    print(f"Error updating flight price: {e}")
                    
        # Process Accommodations
        if not quota_exceeded:
            for acc in meta.get("accommodations", []):
                if not acc.get("is_live_price") and acc.get("location") and acc.get("check_in_date") and acc.get("check_out_date"):
                    try:
                        price = get_live_hotel_price(acc["location"], acc["check_in_date"], acc["check_out_date"], travelers)
                        if price is not None:
                            acc["estimated_price_usd"] = price
                            acc["is_live_price"] = True
                            updated = True
                    except QuotaExceededError:
                        quota_exceeded = True
                        break
                    except Exception as e:
                        print(f"Error updating accommodation price: {e}")
    except QuotaExceededError:
        quota_exceeded = True
                    
    if updated:
        storage.set_trip_metadata(event_id, meta)
        
    return {
        "flights": meta.get("flights", []),
        "accommodations": meta.get("accommodations", []),
        "updated": updated,
        "quota_exceeded": quota_exceeded
    }

@app.delete("/api/trip/{event_id}/flight/{item_id}")
def delete_flight_api(event_id: str, item_id: str):
    meta = storage.get_trip_metadata(event_id)
    if not meta or 'flights' not in meta:
        return {"error": "Trip or flights not found"}
        
    initial_count = len(meta['flights'])
    meta['flights'] = [f for f in meta['flights'] if str(f.get('id')) != str(item_id)]
    
    if len(meta['flights']) < initial_count:
        storage.set_trip_metadata(event_id, meta)
        return {"status": "ok", "deleted": True}
    return {"error": "Flight not found"}

@app.delete("/api/trip/{event_id}/accommodation/{item_id}")
def delete_accommodation_api(event_id: str, item_id: str):
    meta = storage.get_trip_metadata(event_id)
    if not meta or 'accommodations' not in meta:
        return {"error": "Trip or accommodations not found"}
        
    initial_count = len(meta['accommodations'])
    meta['accommodations'] = [a for a in meta['accommodations'] if str(a.get('id')) != str(item_id)]
    
    if len(meta['accommodations']) < initial_count:
        storage.set_trip_metadata(event_id, meta)
        return {"status": "ok", "deleted": True}
    return {"error": "Accommodation not found"}

@app.post("/api/trip/{event_id}/generate_pois")
def generate_pois_api(event_id: str, payload: dict):
    user_prompt = payload.get("prompt", "")
    duration_nights = payload.get("duration_nights", 1)
    
    if not user_prompt:
        return {"error": "Prompt is required"}
        
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"error": "Trip not found"}
        
    from datetime import datetime, timezone
    from models.schemas import TripPlan
    
    trip_obj = TripPlan(
        id=payload.get("event_id"),
        mock_start_date=datetime.fromtimestamp(payload.get("mock_start_date"), tz=timezone.utc),
        mock_end_date=datetime.fromtimestamp(payload.get("mock_end_date"), tz=timezone.utc),
        duration_days=duration_nights,
        location=payload.get("location"),
        timeZone=payload.get("timeZone", "UTC"),
        budget_min_usd=payload.get("budget_min_usd"),
        budget_max_usd=payload.get("budget_max_usd"),
        flight_preferences=payload.get("flight_preferences"),
        attendees=payload.get("attendees", []),
        travelers=payload.get("travelers", 1)
    )
    
    from services.trip_planner import generate_trip_pois
    warning, pois = generate_trip_pois(trip_obj, user_prompt, duration_nights)
    
    # Save back to trip metadata
    if 'pois' not in meta:
        meta['pois'] = []
    
    existing_poi_names = {p.get('name', '').lower() for p in meta['pois']}
    for poi in pois:
        if poi.name.lower() not in existing_poi_names:
            poi_dict = poi.model_dump() if hasattr(poi, 'model_dump') else poi.dict()
            meta['pois'].append(poi_dict)
            existing_poi_names.add(poi.name.lower())
        
    storage.set_trip_metadata(event_id, meta)
    
    return {"budget_warning": warning, "pois": meta['pois']}

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
            
        from services.trip_scheduler import schedule_poi
        event_calendar_id, reason, suggested_fixes = schedule_poi(trip_obj, poi)
        if not event_calendar_id:
            return {"error": reason or "Failed to schedule POI (no available time slot or calendar missing)", "suggested_fixes": suggested_fixes}
            
        # Update POI in DB
        meta['pois'] = [p.model_dump() if hasattr(p, 'model_dump') else p.dict() for p in trip_obj.pois]
        
        if not event_id.startswith("draft_trip_"):
            if "activities" not in meta:
                meta["activities"] = []
            trip_cals = trip_obj.calendar_ids if hasattr(trip_obj, 'calendar_ids') and trip_obj.calendar_ids else []
            if not trip_cals:
                trip_cals = [event_id.split("::", 1)[0] if "::" in event_id else "primary"]
            full_id = f"{trip_cals[0]}::{event_calendar_id}"
            if full_id not in meta["activities"]:
                meta["activities"].append(full_id)
                
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
        
        from services.trip_scheduler import schedule_pois_bulk
        import json
        
        def stream_generator():
            import time as _time
            last_save = 0.0
            dirty = False

            def _sync_meta():
                meta['pois'] = [p.model_dump() if hasattr(p, 'model_dump') else p.dict() for p in trip_obj.pois]
                if not event_id.startswith("draft_trip_"):
                    if "activities" not in meta:
                        meta["activities"] = []
                    trip_cals = trip_obj.calendar_ids if hasattr(trip_obj, 'calendar_ids') and trip_obj.calendar_ids else []
                    if not trip_cals:
                        trip_cals = [event_id.split("::", 1)[0] if "::" in event_id else "primary"]
                    for poi in trip_obj.pois:
                        if poi.event_id and poi.is_scheduled:
                            if not poi.event_id.startswith("draft_poi_") and not poi.event_id.startswith("draft_acc_"):
                                full_id = f"{trip_cals[0]}::{poi.event_id}"
                                if full_id not in meta["activities"]:
                                    meta["activities"].append(full_id)

            try:
                for result in schedule_pois_bulk(trip_obj, poi_ids):
                    if result.get("success"):
                        dirty = True
                        # TinyDB rewrites the whole file per save (~hundreds of ms on a
                        # big trip) — throttle to 1/s; the finally below saves the rest.
                        now = _time.monotonic()
                        if now - last_save >= 1.0:
                            _sync_meta()
                            storage.set_trip_metadata(event_id, meta)
                            last_save = now
                            dirty = False
                    yield json.dumps(result) + "\n"
            except Exception as ex:
                yield json.dumps({"poi_id": None, "success": False, "reason": f"Internal Error: {str(ex)}"}) + "\n"
            finally:
                # Persist everything on completion AND on client cancel (GeneratorExit)
                if dirty:
                    _sync_meta()
                    storage.set_trip_metadata(event_id, meta)

        from fastapi.responses import StreamingResponse
        return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


def _is_calendar_backed_poi(poi: dict) -> bool:
    """A POI that stands in for a real calendar event (committed by Chauffeur or,
    once linking-as-POI lands, an externally-authored event pulled in). Its
    event_id is a real cal id, not a fuzzy draft_poi_ placeholder. These are
    fixed anchors: never auto-unscheduled by clear/rebuild, and the solver
    schedules other POIs around them via its 'locked' mechanism."""
    ev = poi.get("event_id") or ""
    return "::" in ev and not ev.startswith("draft_poi_")


@app.post("/api/trip/{event_id}/unschedule")
def unschedule_pois_api(event_id: str, payload: dict):
    """Remove specific POIs from the timeline WITHOUT deleting anything from the
    calendar — the planning-friendly 'clear the schedule' primitive (per-day or
    per-selection). Calendar-backed anchors are left untouched."""
    poi_ids = set(payload.get("poi_ids", []))
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"status": "ok", "unscheduled": 0}
    n = 0
    for poi in meta.get("pois", []):
        if poi.get("id") in poi_ids and not _is_calendar_backed_poi(poi):
            if poi.get("is_scheduled") or poi.get("scheduled_start"):
                poi["is_scheduled"] = False
                poi["scheduled_start"] = None
                poi["scheduled_end"] = None
                if (poi.get("event_id") or "").startswith("draft_poi_"):
                    poi["event_id"] = None
                n += 1
    if n:
        storage.set_trip_metadata(event_id, meta)
    return {"status": "ok", "unscheduled": n}


@app.post("/api/trip/{event_id}/rebuild")
def rebuild_itinerary_api(event_id: str):
    """Re-solve the itinerary from scratch WITHOUT clearing, unlinking, or
    deleting anything. Planning POIs are un-scheduled and re-placed; calendar-
    backed anchors (committed POIs, and — once linking-as-POI lands — linked real
    events) stay put and the solver routes around them. This is the everyday
    'change some settings, rebuild the schedule' action."""
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        return {"error": "Trip not found"}
    fuzzy_ids = []
    for poi in meta.get("pois", []):
        if _is_calendar_backed_poi(poi):
            continue  # fixed anchor — leave it exactly where it is
        if poi.get("is_scheduled") or poi.get("scheduled_start"):
            poi["is_scheduled"] = False
            poi["scheduled_start"] = None
            poi["scheduled_end"] = None
            if (poi.get("event_id") or "").startswith("draft_poi_"):
                poi["event_id"] = None
        fuzzy_ids.append(poi.get("id"))
    storage.set_trip_metadata(event_id, meta)
    # Reuse the streaming scheduler; already-scheduled anchors are treated as
    # locked placements the solver won't move.
    return schedule_pois_bulk_api(event_id, {"poi_ids": fuzzy_ids})


@app.get("/api/calendar/events")
def list_calendar_events_api(start_date: str = None, end_date: str = None):
    """Raw Google Calendar events in a date range, straight from the calendar —
    for the trip event linker. Deliberately NOT sourced from the solved/cached
    daily schedule (which can be stale and omit an event added after that day was
    last solved — e.g. a dinner booked later shows on every other day but not the
    one whose cache predates it)."""
    settings = storage.get_settings()
    calendar_ids = settings.get('calendar_ids', [])
    if not calendar_ids or not start_date or not end_date:
        return {"events": []}
    from services.calendar import fetch_upcoming_events
    try:
        events = fetch_upcoming_events(calendar_ids, start_date_str=start_date, end_date_str=end_date)
    except Exception as e:
        return {"error": str(e), "events": []}
    out = []
    for ev in events:
        start = getattr(ev, 'start', None)
        out.append({
            "id": getattr(ev, 'id', None),
            "title": getattr(ev, 'title', ''),
            "start": start.isoformat() if hasattr(start, 'isoformat') else (str(start) if start else ''),
            "event_type": getattr(ev, 'event_type', 'standard'),
            "trip_id": getattr(ev, 'trip_id', None),
            "source_event_ids": getattr(ev, 'source_event_ids', []),
        })
    return {"events": out}


@app.post("/api/trip/{event_id}/link_events")
def link_events_api(event_id: str, payload: dict):
    """Link one or more existing calendar events to the trip in a single call:
    set each event config's trip_id, then run the POI sync ONCE so all the
    calendar-backed POIs are created together. Backs the multiselect linker."""
    ids = payload.get("source_event_ids") or []
    if not isinstance(ids, list) or not ids:
        return {"error": "source_event_ids list required"}

    linked = 0
    for src in ids:
        if not src:
            continue
        raw_id = src.split("::", 1)[1] if "::" in src else src
        conf = dict(storage.get_event_config(raw_id) or {"google_id": raw_id})
        conf["trip_id"] = event_id
        storage.set_event_config(raw_id, conf)
        linked += 1

    from services.calendar import get_calendar_service
    try:
        service = get_calendar_service()
    except Exception:
        service = None
    meta = storage.get_trip_metadata(event_id)
    if meta is not None:
        _sync_linked_events_to_pois(meta, event_id, service)

    return {"status": "ok", "linked": linked}


@app.post("/api/trip/{event_id}/unlink_event")
def unlink_event_api(event_id: str, payload: dict):
    """Detach an externally-linked calendar event from the trip: clear the
    Schedule-page event-config link (so the POI sync stops re-creating it) and
    drop its calendar-backed POI now. The Google Calendar event is NEVER deleted
    — unlinking only removes it from THIS trip's plan."""
    source_event_id = payload.get("source_event_id") or ""
    if "::" not in source_event_id:
        return {"error": "source_event_id (cal::id) required"}
    raw_id = source_event_id.split("::", 1)[1]

    cleared = 0
    conf = storage.get_event_config(raw_id)
    if conf and conf.get("trip_id"):
        conf = dict(conf)
        conf["trip_id"] = None
        storage.set_event_config(raw_id, conf)
        cleared = 1

    meta = storage.get_trip_metadata(event_id)
    if meta:
        before = len(meta.get("pois", []))
        meta["pois"] = [p for p in meta.get("pois", [])
                        if p.get("source_event_id") != source_event_id]
        if len(meta.get("pois", [])) != before:
            storage.set_trip_metadata(event_id, meta)

    return {"status": "ok", "cleared": cleared}


@app.get("/api/trip/{event_id}/rules")
def get_trip_rules_api(event_id: str):
    """Stored TripRules plus a read-only view of rules derived from POI settings (design §5.3)."""
    try:
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
        from models.schemas import TripMetadata
        trip_obj = TripMetadata(**meta)
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        derived = []
        for p in trip_obj.pois:
            if p.valid_days_of_week:
                days = "/".join(day_names[d] for d in sorted(set(p.valid_days_of_week)) if 0 <= d <= 6)
                derived.append({"poi_id": p.id, "description": f"{p.name}: only on {days}"})
            if getattr(p, 'meal_type', None):
                desc = f"{p.name}: {p.meal_type}"
                if getattr(p, 'dining_style', None):
                    desc += f" ({p.dining_style} dining)"
                derived.append({"poi_id": p.id, "description": desc})
            if getattr(p, 'parent_container', None):
                parent = next((q for q in trip_obj.pois if q.id == p.parent_container), None)
                if parent:
                    derived.append({"poi_id": p.id, "description": f"{p.name}: inside {parent.name}"})
            if getattr(p, 'is_background', False) and (getattr(p, 'days_claimed', 1) or 1) > 1:
                derived.append({"poi_id": p.id, "description": f"{p.name}: anchors {p.days_claimed} full days"})
        return {"rules": [r.model_dump() for r in trip_obj.rules], "derived": derived}
    except Exception as e:
        return {"error": str(e)}

@app.patch("/api/trip/{event_id}/rules/{rule_id}")
def patch_trip_rule_api(event_id: str, rule_id: str, payload: dict):
    """v1 rules panel write op: enable/disable a rule."""
    try:
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
        rule = next((r for r in meta.get('rules', []) if r.get('id') == rule_id), None)
        if not rule:
            return {"error": "Rule not found"}
        if 'is_enabled' in payload:
            rule['is_enabled'] = bool(payload['is_enabled'])
        storage.set_trip_metadata(event_id, meta)
        return {"status": "ok", "rule": rule}
    except Exception as e:
        return {"error": str(e)}

@app.put("/api/trip/{event_id}/poi/{poi_id}")
def edit_trip_poi_api(event_id: str, poi_id: str, payload: dict):
    try:
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
            
        from models.schemas import TripMetadata
        trip_obj = TripMetadata(**meta)
        
        poi = next((p for p in trip_obj.pois if p.id == poi_id), None)
        if not poi:
            return {"error": "POI not found"}
            
        # Update allowed fields
        if "name" in payload: poi.name = payload["name"]
        if "location" in payload: poi.location = payload["location"]
        if "category" in payload: poi.category = payload["category"]
        if "duration_mins" in payload: poi.duration_mins = payload["duration_mins"]
        if "priority" in payload: poi.priority = payload["priority"]
        if "ideal_time_start" in payload: poi.ideal_time_start = payload["ideal_time_start"]
        if "ideal_time_end" in payload: poi.ideal_time_end = payload["ideal_time_end"]
        if "description" in payload: poi.description = payload["description"]
        if "notes" in payload: poi.notes = payload["notes"]
        if "is_background" in payload: poi.is_background = payload["is_background"]
        if "valid_days_of_week" in payload: poi.valid_days_of_week = payload["valid_days_of_week"]
        
        meta['pois'] = [p.model_dump() if hasattr(p, 'model_dump') else p.dict() for p in trip_obj.pois]
        storage.set_trip_metadata(event_id, meta)
        
        return {"status": "ok", "poi": next((p for p in meta['pois'] if p['id'] == poi_id), {})}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.post("/api/trip/{event_id}/accommodation")
def add_trip_accommodation_api(event_id: str, payload: dict):
    try:
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
            
        from models.schemas import TripMetadata, TripAccommodation
        trip_obj = TripMetadata(**meta)
        
        acc = TripAccommodation(
            name=payload.get("name", "New Accommodation"),
            location=payload.get("location", ""),
            check_in_date=payload.get("check_in_date"),
            check_out_date=payload.get("check_out_date"),
            notes=payload.get("notes")
        )
        
        if not trip_obj.is_draft and acc.check_in_date and acc.check_out_date:
            from services import calendar
            settings = storage.get_settings()
            cals = settings.get('calendar_ids', [])
            if cals:
                # Create an all-day or background event
                acc.event_id = calendar.create_event(
                    calendar_id=cals[0],
                    title=f"Stay: {acc.name}",
                    start=f"{acc.check_in_date}T15:00:00",
                    end=f"{acc.check_out_date}T11:00:00",
                    location=acc.location,
                    description=acc.notes,
                    trip_id=trip_obj.id,
                    event_type="trip_background"
                )
        
        if 'accommodations' not in meta:
            meta['accommodations'] = []
            
        acc_dict = acc.model_dump() if hasattr(acc, 'model_dump') else acc.dict()
        meta['accommodations'].append(acc_dict)
        storage.set_trip_metadata(event_id, meta)
        
        return {"status": "ok", "accommodation": acc_dict}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.put("/api/trip/{event_id}/accommodation/{acc_id}")
def edit_trip_accommodation_api(event_id: str, acc_id: str, payload: dict):
    try:
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
            
        from models.schemas import TripMetadata
        trip_obj = TripMetadata(**meta)
        
        acc = next((a for a in trip_obj.accommodations if a.id == acc_id), None)
        if not acc:
            return {"error": "Accommodation not found"}
            
        if "name" in payload: acc.name = payload["name"]
        if "location" in payload: acc.location = payload["location"]
        if "check_in_date" in payload: acc.check_in_date = payload["check_in_date"]
        if "check_out_date" in payload: acc.check_out_date = payload["check_out_date"]
        if "notes" in payload: acc.notes = payload["notes"]
        
        if not trip_obj.is_draft and acc.event_id:
            from services import calendar
            details = {
                "title": f"Stay: {acc.name}",
                "location": acc.location,
                "description": acc.notes or "",
            }
            if acc.check_in_date and acc.check_out_date:
                details["start"] = f"{acc.check_in_date}T15:00:00+00:00"
                details["end"] = f"{acc.check_out_date}T11:00:00+00:00"
                
            # We assume the event is on the primary calendar; ideally we'd look up the exact source_event_id
            settings = storage.get_settings()
            cals = settings.get('calendar_ids', [])
            if cals:
                source_id = f"{cals[0]}::{acc.event_id}"
                calendar.update_event_details([source_id], details)
                
        meta['accommodations'] = [a.model_dump() if hasattr(a, 'model_dump') else a.dict() for a in trip_obj.accommodations]
        storage.set_trip_metadata(event_id, meta)
        
        return {"status": "ok", "accommodation": next((a for a in meta['accommodations'] if a['id'] == acc_id), {})}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.delete("/api/trip/{event_id}/accommodation/{acc_id}")
def delete_trip_accommodation_api(event_id: str, acc_id: str):
    try:
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            return {"error": "Trip not found"}
            
        from models.schemas import TripMetadata
        trip_obj = TripMetadata(**meta)
        
        acc = next((a for a in trip_obj.accommodations if a.id == acc_id), None)
        if not acc:
            return {"error": "Accommodation not found"}
            
        if not trip_obj.is_draft and acc.event_id:
            from services import calendar
            settings = storage.get_settings()
            cals = settings.get('calendar_ids', [])
            if cals:
                calendar.delete_event(cals[0], acc.event_id)
                
        trip_obj.accommodations = [a for a in trip_obj.accommodations if a.id != acc_id]
        meta['accommodations'] = [a.model_dump() if hasattr(a, 'model_dump') else a.dict() for a in trip_obj.accommodations]
        storage.set_trip_metadata(event_id, meta)
        
        return {"status": "ok"}
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

# --- V2 Agentic Core API ---

CHAT_EVENTS = []

class ConverseRequest(BaseModel):
    text: str
    language: str = "en"
    conversation_id: Optional[str] = None

@app.post("/api/v2/converse")
def converse_ha_assist(req: ConverseRequest):
    """
    Endpoint for Home Assistant Assist Pipeline to send transcribed text.
    Acts as a Custom Conversation Agent webhook. When HA supplies a
    conversation_id (stable across follow-up turns of one voice session),
    history is threaded through the same conversation store as /api/chat so
    voice gets multi-turn memory. Titles are set without an LLM call.
    """
    from services.agent_router import process_agent_request

    converse_start = time.time()
    try:
        conv_history = []
        conv_id = None
        if req.conversation_id:
            # Namespace HA's id so it can never collide with widget conversations.
            conv_id = f"voice-{req.conversation_id}"
            conv = storage.get_conversation(conv_id)
            if not conv:
                title = req.text if len(req.text) <= 60 else req.text[:57] + "..."
                storage.create_conversation({
                    "id": conv_id,
                    "type": "voice",
                    "mode": "standard",
                    "title": f"🎙️ {title}",
                    "context_id": None,
                    "messages": [],
                    "created_at": time.time(),
                    "updated_at": time.time(),
                })
            else:
                conv_history = conv.get("messages", [])
            storage.add_message_to_conversation(conv_id, {'role': 'user', 'content': req.text, 'timestamp': time.time()})

        res = process_agent_request(req.text, history=conv_history)

        if conv_id:
            storage.add_message_to_conversation(conv_id, {'role': 'assistant', 'content': res.get("message", "Done."), 'timestamp': time.time()})
        
        # Trigger global dashboard update event if a target was modified
        if res.get("target_element_id"):
            global LAST_UPDATE_TIME
            LAST_UPDATE_TIME = time.time()

        # Agent tools write overrides straight to storage; without a re-solve
        # the dashboard would refetch the stale cached schedule until the next
        # Sync Now / poll. Non-blocking, so the spoken reply isn't delayed.
        if res.get("schedule_dirty"):
            trigger_background_refresh()

        # Push to SSE stream for frontend
        import json
        event_data = {
            "target_element_id": res.get("target_element_id"),
            "reply": res.get("message", "Done.")
        }
        CHAT_EVENTS.append(event_data)
            
        # Return format expected by Home Assistant Conversation integration
        logger.info(f"[agent-timing] /api/v2/converse total {time.time() - converse_start:.1f}s")
        return {
            "response": {
                "speech": {
                    "plain": {
                        "speech": res.get("message", "I did not understand that."),
                        "extra_data": None
                    }
                },
                "card": {},
                "language": req.language,
                "response_type": "action_done",
                "data": {
                    "targets": [],
                    "success": [],
                    "failed": []
                }
            }
        }
    except Exception as e:
        import traceback
        logger.error(f"Error in converse API: {traceback.format_exc()}")
        return {"error": str(e)}

@app.get("/api/v2/chat/stream")
async def stream_agent_chat():
    """
    Websocket/SSE endpoint for the Frontend to receive agent chat bubbles
    and DOM target coordinates for rendering context-anchored chat bubbles.
    """
    import json
    async def chat_event_generator():
        last_index = len(CHAT_EVENTS)
        last_ping = time.time()
        try:
            while True:
                await asyncio.sleep(0.5)
                now = time.time()
                if len(CHAT_EVENTS) > last_index:
                    for i in range(last_index, len(CHAT_EVENTS)):
                        yield f"data: {json.dumps(CHAT_EVENTS[i])}\n\n"
                    last_index = len(CHAT_EVENTS)
                    last_ping = now
                elif now - last_ping > 15:
                    yield ": ping\n\n"
                    last_ping = now
        except asyncio.CancelledError:
            pass
            
    return StreamingResponse(chat_event_generator(), media_type="text/event-stream")
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

# --- ICS Feed Subscriptions API (intake arc phase 1) ---

class IcsFeedCreate(BaseModel):
    url: str
    calendar_id: str
    name: Optional[str] = None

class IcsFeedUpdate(BaseModel):
    name: Optional[str] = None
    calendar_id: Optional[str] = None
    enabled: Optional[bool] = None

def _public_ics_feed(f: dict) -> dict:
    """The event_map is internal bookkeeping (can be hundreds of entries)."""
    return {k: v for k, v in f.items() if k != 'event_map'}

@app.get("/api/ics_feeds")
def list_ics_feeds():
    return [_public_ics_feed(f) for f in storage.get_ics_feeds()]

@app.post("/api/ics_feeds")
def create_ics_feed(req: IcsFeedCreate, background_tasks: BackgroundTasks):
    from services import ics_sync
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Feed URL is required")
    try:
        parsed = ics_sync.fetch_and_parse(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read that ICS feed: {e}")

    name = (req.name or '').strip() or parsed.get('name')
    if not name:
        name = url.split('/')[2] if '://' in url else url
    feed_id = storage.add_ics_feed({
        'url': url,
        'name': name,
        'calendar_id': req.calendar_id,
        'created_at': datetime.now().astimezone().isoformat(),
    })

    def _initial_sync():
        feed = storage.get_ics_feed(feed_id)
        if feed:
            res = ics_sync.sync_feed(feed)
            if res.get('added') or res.get('updated') or res.get('removed'):
                trigger_background_refresh()

    background_tasks.add_task(_initial_sync)
    return {"id": feed_id, "name": name, "event_count": len(parsed['items']),
            "status": "created — first sync running in background"}

@app.put("/api/ics_feeds/{feed_id}")
def update_ics_feed(feed_id: str, req: IcsFeedUpdate):
    feed = storage.get_ics_feed(feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    updates = {}
    if req.name is not None:
        updates['name'] = req.name.strip()
    if req.enabled is not None:
        updates['enabled'] = req.enabled
    if req.calendar_id is not None and req.calendar_id != feed.get('calendar_id'):
        # Retargeting calendars: the old calendar's future events would be
        # orphaned, so refuse — delete and re-add the feed instead.
        raise HTTPException(status_code=400,
                            detail="Target calendar can't be changed; delete the feed and re-add it.")
    if updates:
        storage.update_ics_feed(feed_id, updates)
    return {"status": "updated"}

@app.post("/api/ics_feeds/{feed_id}/sync")
def sync_ics_feed_now(feed_id: str, background_tasks: BackgroundTasks):
    from services import ics_sync
    feed = storage.get_ics_feed(feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    res = ics_sync.sync_feed(feed)
    if res.get('added') or res.get('updated') or res.get('removed'):
        background_tasks.add_task(trigger_background_refresh)
    return res

@app.delete("/api/ics_feeds/{feed_id}")
def delete_ics_feed(feed_id: str, background_tasks: BackgroundTasks,
                    remove_events: bool = False):
    from services import ics_sync
    feed = storage.get_ics_feed(feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    removed = 0
    if remove_events:
        removed = ics_sync.remove_feed_events(feed)
        if removed:
            background_tasks.add_task(trigger_background_refresh)
    storage.delete_ics_feed(feed_id)
    return {"status": "deleted", "events_removed": removed}

# --- Email Intake API (intake arc phase 2) ---

class IngestConfig(BaseModel):
    ingest_email_enabled: Optional[bool] = None
    ingest_email_host: Optional[str] = None
    ingest_email_user: Optional[str] = None
    ingest_email_password: Optional[str] = None
    ingest_sender_defaults: Optional[list] = None

class ProposalApprove(BaseModel):
    calendar_id: str
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None

@app.get("/api/ingest/config")
def get_ingest_config():
    s = storage.get_settings() or {}
    return {
        'ingest_email_enabled': bool(s.get('ingest_email_enabled')),
        'ingest_email_host': s.get('ingest_email_host') or 'imap.gmail.com',
        'ingest_email_user': s.get('ingest_email_user') or '',
        'has_password': bool(s.get('ingest_email_password')),
        'ingest_sender_defaults': s.get('ingest_sender_defaults') or [],
    }

@app.post("/api/ingest/config")
def set_ingest_config(cfg: IngestConfig):
    updates = {k: v for k, v in cfg.model_dump().items() if v is not None}
    # An empty password field in the UI means "keep the stored one".
    if updates.get('ingest_email_password') == '':
        updates.pop('ingest_email_password')
    if 'ingest_sender_defaults' in updates:
        updates['ingest_sender_defaults'] = [
            {'pattern': (e.get('pattern') or '').strip(),
             'calendar_id': (e.get('calendar_id') or '').strip() or None}
            for e in updates['ingest_sender_defaults']
            if isinstance(e, dict) and (e.get('pattern') or '').strip()
        ]
    storage.patch_settings(updates)
    return {"status": "updated"}

@app.post("/api/ingest/run")
def run_ingest_now():
    from services import email_ingest
    summary = email_ingest.run_ingest()
    # Pending count lets the UI tell "nothing new" apart from "the background
    # poll beat you to it moments ago" — both report checked: 0.
    summary['pending'] = len(storage.get_proposals('proposed'))
    return summary

@app.get("/api/ingest/log")
def ingest_log(limit: int = 50):
    return storage.get_ingest_log(limit=limit)

@app.get("/api/proposals")
def list_proposals(status: str = 'proposed'):
    props = storage.get_proposals(status if status != 'all' else None)
    return sorted(props, key=lambda p: p.get('start') or '')

@app.post("/api/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, req: ProposalApprove, background_tasks: BackgroundTasks):
    from services import calendar as gcal
    prop = storage.get_proposal(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if prop.get('status') != 'proposed':
        raise HTTPException(status_code=409, detail=f"Proposal is already {prop.get('status')}")

    title = (req.title or '').strip() or prop['title']
    start = req.start or prop['start']
    end = req.end or prop['end']
    description_parts = []
    if prop.get('notes'):
        description_parts.append(prop['notes'])
    description_parts.append(f"From family email: {prop.get('source_from', '')} — {prop.get('source_subject', '')}")

    if prop.get('all_day'):
        body_start, body_end = {'date': start[:10]}, {'date': end[:10]}
    else:
        body_start, body_end = {'dateTime': start}, {'dateTime': end}
    body = {
        'summary': title,
        'start': body_start,
        'end': body_end,
        'description': '\n'.join(description_parts),
        'extendedProperties': {'private': {'intake_proposal_id': proposal_id}},
    }
    if prop.get('location'):
        body['location'] = prop['location']

    gid = gcal.insert_event(req.calendar_id, body)
    if not gid:
        raise HTTPException(status_code=502, detail="Google Calendar rejected the event")
    storage.update_proposal(proposal_id, {
        'status': 'approved', 'calendar_id': req.calendar_id,
        'created_event_id': gid, 'title': title, 'start': start, 'end': end,
    })
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "approved", "event_id": gid}

@app.post("/api/proposals/{proposal_id}/ignore")
def ignore_proposal(proposal_id: str):
    prop = storage.get_proposal(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
    storage.update_proposal(proposal_id, {'status': 'ignored'})
    return {"status": "ignored"}

# --- Family Members API (overlay over drivers/passengers) ---

def _public_member(m: dict) -> dict:
    """Strip PIN secrets; expose has_pin instead."""
    out = {k: v for k, v in m.items() if k not in ('pin_hash', 'pin_salt', 'pin')}
    out['has_pin'] = bool(m.get('pin_hash'))
    return out

@app.get("/api/members")
def get_members():
    members = storage.get_all_members()
    drivers = {d.get('id'): d for d in storage.get_all_drivers()}
    passengers = {p.get('id'): p for p in storage.get_all_passengers()}
    out = []
    for m in members:
        pub = _public_member(m)
        pub['driver'] = drivers.get(m.get('driver_id'))
        pub['passenger'] = passengers.get(m.get('passenger_id'))
        out.append(pub)
    return out

@app.post("/api/members")
def create_member(member: FamilyMember):
    data = member.model_dump()
    storage.add_member(data)
    return {"id": data['id'], "status": "created"}

@app.put("/api/members/{member_id}")
def update_member_endpoint(member_id: str, updates: dict):
    # Partial update; id/links are managed via merge/split, PINs via the pin
    # endpoints — never via blind PUT.
    for field in ('id', 'doc_id', 'driver', 'passenger', 'pin_hash', 'pin_salt', 'has_pin', 'pin'):
        updates.pop(field, None)
    if 'role' in updates:
        if updates['role'] not in ('parent', 'adult', 'child', 'helper'):
            raise HTTPException(status_code=400, detail="Invalid role")
        updates['is_child'] = updates['role'] == 'child'
    if not storage.update_member(member_id, updates):
        raise HTTPException(status_code=404, detail="Member not found")
    return {"status": "updated"}

@app.delete("/api/members/{member_id}")
def delete_member_endpoint(member_id: str, force: bool = False):
    member = storage.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if (member.get('driver_id') or member.get('passenger_id')) and not force:
        raise HTTPException(status_code=409,
                            detail="Member is linked to a driver/passenger; pass force=true to delete anyway")
    storage.delete_member(member_id)
    return {"status": "deleted"}

class MergeMembersRequest(BaseModel):
    keep_id: str
    absorb_id: str

@app.post("/api/members/merge")
def merge_members_endpoint(req: MergeMembersRequest):
    result = storage.merge_members(req.keep_id, req.absorb_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return _public_member(result)

class SplitMemberRequest(BaseModel):
    link: str  # 'driver' | 'passenger'

@app.post("/api/members/{member_id}/split")
def split_member_endpoint(member_id: str, req: SplitMemberRequest):
    if req.link not in ('driver', 'passenger'):
        raise HTTPException(status_code=400, detail="link must be 'driver' or 'passenger'")
    result = storage.split_member(member_id, req.link)
    if result is None:
        raise HTTPException(status_code=400,
                            detail="Member not found, link empty, or it is the member's only link")
    return _public_member(result)

@app.get("/api/members/resolve")
def resolve_member(driver_id: Optional[str] = None, passenger_id: Optional[str] = None):
    member = None
    if driver_id:
        member = storage.get_member_by_driver_id(driver_id)
    elif passenger_id:
        member = storage.get_member_by_passenger_id(passenger_id)
    if not member:
        raise HTTPException(status_code=404, detail="No member for that identity")
    return _public_member(member)

# --- Member PIN auth (identity switching + privileged actions) ---

_PIN_ATTEMPTS = {}  # member_id -> {'fails': int, 'locked_until': ts}

def _pin_rate_check(member_id: str):
    entry = _PIN_ATTEMPTS.get(member_id)
    if entry and time.time() < entry.get('locked_until', 0):
        raise HTTPException(status_code=429,
                            detail="Too many attempts — try again in a moment")

def _pin_rate_record(member_id: str, ok: bool):
    if ok:
        _PIN_ATTEMPTS.pop(member_id, None)
        return
    entry = _PIN_ATTEMPTS.setdefault(member_id, {'fails': 0, 'locked_until': 0})
    entry['fails'] += 1
    if entry['fails'] >= 5:
        entry['fails'] = 0
        entry['locked_until'] = time.time() + 30

def _valid_pin_format(pin: str) -> bool:
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 8

class MemberAuthRequest(BaseModel):
    pin: Optional[str] = None

@app.post("/api/members/{member_id}/auth")
def member_auth(member_id: str, req: MemberAuthRequest):
    """Verify PIN (when set) and mint a per-device token. Members without a
    PIN authenticate freely — same household trust as before, hardened only
    where someone chose to be hardened."""
    member = storage.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.get('pin_hash'):
        _pin_rate_check(member_id)
        ok = storage.verify_member_pin(member_id, req.pin or '')
        _pin_rate_record(member_id, ok)
        if not ok:
            raise HTTPException(status_code=403, detail="Wrong PIN")
    token = storage.create_member_token(member_id)
    return {"token": token, "member": _public_member(member)}

class SetPinRequest(BaseModel):
    pin: str
    current_pin: Optional[str] = None

@app.post("/api/members/{member_id}/pin")
def set_pin(member_id: str, req: SetPinRequest):
    """Set/change own PIN. First set is open (self-serve on first login);
    changing requires the current PIN. Parent resets go via /pin/clear."""
    member = storage.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if not _valid_pin_format(req.pin):
        raise HTTPException(status_code=400, detail="PIN must be 4-8 digits")
    if member.get('pin_hash'):
        _pin_rate_check(member_id)
        ok = storage.verify_member_pin(member_id, req.current_pin or '')
        _pin_rate_record(member_id, ok)
        if not ok:
            raise HTTPException(status_code=403, detail="Current PIN is wrong")
    storage.set_member_pin(member_id, req.pin)
    return {"status": "ok"}

@app.post("/api/members/{member_id}/pin/clear")
def clear_pin(member_id: str):
    """Parent reset from the (dashboard-trusted) config page: clears the PIN
    and revokes that member's device tokens."""
    if not storage.get_member(member_id):
        raise HTTPException(status_code=404, detail="Member not found")
    storage.clear_member_pin(member_id)
    storage.delete_member_tokens(member_id)
    return {"status": "cleared"}

def require_parent_token(token: Optional[str]):
    """Guard for privileged actions (chore verification, rewards admin...).
    Returns the parent member or raises."""
    member = storage.get_member_by_token(token or '')
    if not member or member.get('role') != 'parent':
        raise HTTPException(status_code=403, detail="Parent authorization required")
    return member

# --- Home Assistant bridge API (services/ha_api.py) ---

@app.get("/api/ha/status")
def ha_status():
    from services import ha_api
    available = ha_api.is_available()
    result = {
        "mode": ha_api.mode(),
        "available": available,
        "persons": 0,
        "device_trackers": 0,
        "media_players": 0,
        "notify_services": 0,
    }
    if available:
        result.update(
            persons=len(ha_api.get_entities('person')),
            device_trackers=len(ha_api.get_entities('device_tracker')),
            media_players=len(ha_api.get_entities('media_player')),
            notify_services=len(ha_api.list_notify_services()),
        )
    return result

@app.get("/api/ha/entities")
def ha_entities(domain: str):
    from services import ha_api
    return ha_api.get_entities(domain)

@app.get("/api/ha/notify_services")
def ha_notify_services():
    from services import ha_api
    return ha_api.list_notify_services()

class TestNotifyRequest(BaseModel):
    member_id: str

@app.post("/api/ha/test_notify")
def ha_test_notify(req: TestNotifyRequest):
    from services import ha_api
    member = storage.get_member(req.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    svc = member.get('notify_service')
    if not svc:
        raise HTTPException(status_code=400, detail="Member has no notify_service configured")
    svc_name = svc.split('.', 1)[1] if '.' in svc else svc
    result = ha_api.call_service('notify', svc_name, {
        "title": "Chauffeur",
        "message": f"Test notification for {member.get('name', 'member')} 🚗",
    })
    if result is None:
        raise HTTPException(status_code=502, detail="Home Assistant service call failed")
    return {"status": "sent", "service": svc}

# --- Family Messaging API ---
# Delivery has three lanes: an addressed SSE stream for foreground clients,
# web push (VAPID, member-keyed subscriptions), and HA companion notify.
# SSE is foreground-only on iOS by design — push is the background channel.

MESSAGE_EVENTS = []  # ring buffer: {'seq', 'channel_id', 'recipients': [member ids] | None (=everyone)}
_MESSAGE_SEQ = 0

def _push_message_event(channel_id, recipients):
    global _MESSAGE_SEQ
    _MESSAGE_SEQ += 1
    MESSAGE_EVENTS.append({'seq': _MESSAGE_SEQ, 'channel_id': channel_id,
                           'recipients': recipients})
    del MESSAGE_EVENTS[:-200]

def send_push_to_member(member_id, title, body, url=None):
    """Web push to every device subscribed for this member. Same VAPID keys
    and dead-subscription pruning as the driver-keyed send_push."""
    from pywebpush import webpush, WebPushException
    import json as _json
    for sub in storage.get_push_subscriptions_for_member(member_id):
        try:
            webpush(
                subscription_info=sub["subscription"],
                data=_json.dumps({
                    "title": title,
                    "body": body,
                    "data": {"navigate_url": url},
                }),
                vapid_private_key=VAPID_PRIVATE_KEY_PATH,
                vapid_claims={"sub": "mailto:admin@example.com"}
            )
        except WebPushException as ex:
            code = getattr(getattr(ex, 'response', None), 'status_code', None)
            if code in (404, 410):
                endpoint = (sub.get("subscription") or {}).get("endpoint")
                if endpoint:
                    try:
                        storage.delete_push_subscription_by_endpoint(endpoint)
                    except Exception as prune_ex:
                        print(f"Failed to prune subscription: {prune_ex}")
            else:
                print(f"Member push failed for {member_id} (HTTP {code}): {repr(ex)}")
        except Exception as ex:
            print(f"Member push failed for {member_id}: {repr(ex)}")

def _channel_recipient_members(channel):
    members = storage.get_all_members()
    if channel.get('kind') == 'dm':
        ids = set(channel.get('member_ids') or [])
        return [m for m in members if m['id'] in ids]
    # family + event channels are household-wide; helpers are outside it
    return [m for m in members if m.get('role') != 'helper']

def _fanout_message_notifications(channel, message):
    """Web push + HA notify to every recipient except the sender. A member
    with both configured gets both (accepted v1 tradeoff, no dedupe)."""
    from services import ha_api
    try:
        sender = storage.get_member(message['sender_member_id']) or {}
        sender_name = sender.get('name', 'Family')
        kind = channel.get('kind')
        if kind == 'dm':
            title = sender_name
        elif kind == 'event':
            title = f"{sender_name} · {channel.get('title') or 'Event chat'}"
        else:
            title = f"{sender_name} · Family"
        body = (message.get('body') or '')[:180]
        base = (storage.get_settings().get('public_base_url') or '').rstrip('/')
        url = f"{base}/app?open_channel={channel['id']}" if base \
            else f"/app?open_channel={channel['id']}"
        for m in _channel_recipient_members(channel):
            if m['id'] == message['sender_member_id']:
                continue
            send_push_to_member(m['id'], title, body, url)
            svc = m.get('notify_service')
            if svc:
                svc_name = svc.split('.', 1)[1] if '.' in svc else svc
                payload = {"title": title, "message": body}
                if base:
                    payload["data"] = {"url": url}
                ha_api.call_service('notify', svc_name, payload)
    except Exception as e:
        print(f"Message notification fan-out failed: {e}")

# --- Music Assistant bridge API (control + search over REST; no WebSocket) ---

_MA_CONFIG_ENTRY = {'id': None, 'checked': False}

def _ma_entry_id():
    from services import ha_api
    if not _MA_CONFIG_ENTRY['checked']:
        _MA_CONFIG_ENTRY['id'] = ha_api.get_config_entry_id('music_assistant')
        _MA_CONFIG_ENTRY['checked'] = True
    return _MA_CONFIG_ENTRY['id']

@app.get("/api/ha/media_players")
def ha_media_players(ma_only: bool = True):
    """media_player entities. By default only Music Assistant's own players
    (identified by the mass_player_type attribute MA stamps on its entities)
    — HA instances accumulate dozens of cast/TV/receiver players that MA
    can't target. Falls back to the full list if no MA players are found."""
    from services import ha_api
    out = []
    for s in ha_api.get_states(ttl=5):
        eid = s.get('entity_id', '')
        if not eid.startswith('media_player.'):
            continue
        attrs = s.get('attributes') or {}
        out.append({
            'entity_id': eid,
            'name': attrs.get('friendly_name') or eid,
            'state': s.get('state'),
            'media_title': attrs.get('media_title'),
            'media_artist': attrs.get('media_artist'),
            'entity_picture': attrs.get('entity_picture'),
            'volume_level': attrs.get('volume_level'),
            'supported_features': attrs.get('supported_features'),
            'device_class': attrs.get('device_class'),
            'is_ma_player': 'mass_player_type' in attrs,
        })
    if ma_only:
        ma_players = [p for p in out if p['is_ma_player']]
        if ma_players:
            out = ma_players
    return sorted(out, key=lambda e: (e['name'] or '').lower())

_HA_IMAGE_PREFIXES = ('/api/media_player_proxy/', '/api/image_proxy/', '/api/image/')

@app.get("/api/ha/image64/{encoded}")
def ha_image64(encoded: str, request: Request):
    """Same as /api/ha/image but with the HA path base64url-encoded into a
    clean path segment — '?path=%2Fapi%2F...' (encoded slashes) reads like a
    traversal probe to WAFs/reverse proxies and got dropped on some client
    network paths."""
    import base64
    try:
        path = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('utf-8')
    except Exception:
        raise HTTPException(status_code=400, detail="Bad encoding")
    return ha_image(path=path, request=request)

@app.get("/api/ha/image")
def ha_image(path: str, request: Request = None):
    """Proxy HA-relative artwork (entity_picture) so browsers on the
    Chauffeur origin can render it. Allowlisted image paths only — this must
    not become a generic authenticated proxy into HA."""
    import time as _time
    from services import ha_api
    ua = ''
    if request is not None:
        ua = (request.headers.get('user-agent') or '')[:60]
    if path.startswith(('http://', 'https://')):
        # Absolute artwork URLs (MA's own image proxy on the LAN, blocked in
        # browsers as mixed content). LAN/private hosts only — this must not
        # become an open proxy to the internet.
        from urllib.parse import urlparse
        import ipaddress
        host = urlparse(path).hostname or ''
        try:
            lan = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
        except ValueError:
            lan = host == 'localhost' or host.endswith('.local')
        if not lan:
            print(f"[ha_image] REJECTED non-LAN url={path[:80]} ua={ua}")
            raise HTTPException(status_code=400, detail="Host not allowed")
    elif not path.startswith(_HA_IMAGE_PREFIXES) or '..' in path:
        print(f"[ha_image] REJECTED path={path[:80]} ua={ua}")
        raise HTTPException(status_code=400, detail="Path not allowed")
    started = _time.time()
    result = ha_api.fetch_binary(path)
    ms = int((_time.time() - started) * 1000)
    if result is None:
        print(f"[ha_image] UPSTREAM-FAIL {ms}ms path={path[:80]} ua={ua}")
        raise HTTPException(status_code=502, detail="Could not fetch image from Home Assistant")
    content, content_type = result
    print(f"[ha_image] OK {len(content)}b {content_type} {ms}ms ua={ua}")
    return Response(content=content, media_type=content_type,
                    headers={'Cache-Control': 'max-age=30'})

class MediaCommandRequest(BaseModel):
    command: str  # play | pause | next | previous | volume_set | volume_mute
    volume: Optional[float] = None
    mute: Optional[bool] = None

@app.post("/api/ha/media_players/{entity_id}/command")
def ha_media_command(entity_id: str, req: MediaCommandRequest):
    from services import ha_api
    service_map = {
        'play': ('media_play', {}),
        'pause': ('media_pause', {}),
        'next': ('media_next_track', {}),
        'previous': ('media_previous_track', {}),
        'volume_set': ('volume_set', {'volume_level': req.volume}),
        'volume_mute': ('volume_mute', {'is_volume_muted': bool(req.mute)}),
    }
    if req.command not in service_map:
        raise HTTPException(status_code=400, detail=f"Unknown command {req.command}")
    service, extra = service_map[req.command]
    if req.command == 'volume_set' and req.volume is None:
        raise HTTPException(status_code=400, detail="volume required for volume_set")
    result = ha_api.call_service('media_player', service,
                                 {'entity_id': entity_id, **extra})
    if result is None:
        raise HTTPException(status_code=502, detail="Home Assistant service call failed")
    return {"status": "ok"}

@app.get("/api/music/search")
def music_search(q: str, media_type: Optional[str] = None, limit: int = 8):
    from services import ha_api
    entry = _ma_entry_id()
    if not entry:
        raise HTTPException(status_code=503, detail="Music Assistant integration not found")
    payload = {'config_entry_id': entry, 'name': q, 'limit': limit}
    if media_type:
        payload['media_type'] = [media_type]
    result = ha_api.call_service('music_assistant', 'search', payload, return_response=True)
    if result is None:
        raise HTTPException(status_code=502, detail="Music Assistant search failed")
    return result.get('service_response', result)

@app.get("/api/music/favorites")
def music_favorites(media_type: str = 'playlist', limit: int = 25):
    from services import ha_api
    entry = _ma_entry_id()
    if not entry:
        raise HTTPException(status_code=503, detail="Music Assistant integration not found")
    result = ha_api.call_service('music_assistant', 'get_library', {
        'config_entry_id': entry, 'media_type': media_type,
        'favorite': True, 'limit': limit,
    }, return_response=True)
    if result is None:
        raise HTTPException(status_code=502, detail="Music Assistant get_library failed")
    return result.get('service_response', result)

@app.get("/api/music/queue")
def music_queue(entity_id: str):
    from services import ha_api
    result = ha_api.call_service('music_assistant', 'get_queue',
                                 {'entity_id': entity_id}, return_response=True)
    if result is None:
        raise HTTPException(status_code=502, detail="Music Assistant get_queue failed")
    return result.get('service_response', result)

class MusicPlayRequest(BaseModel):
    entity_id: str
    media_id: str
    media_type: Optional[str] = None
    enqueue: Optional[str] = None  # play | next | add | replace

@app.post("/api/music/play")
def music_play(req: MusicPlayRequest):
    from services import ha_api
    payload = {'entity_id': req.entity_id, 'media_id': req.media_id}
    if req.media_type:
        payload['media_type'] = req.media_type
    if req.enqueue:
        payload['enqueue'] = req.enqueue
    result = ha_api.call_service('music_assistant', 'play_media', payload)
    if result is None:
        raise HTTPException(status_code=502, detail="Music Assistant play_media failed")
    return {"status": "ok"}

# --- Chores + points API ---
# Marketplace: parents post chores (open-admin config page, same trust as the
# rest of the dashboard), members claim/complete them, VERIFICATION is the
# integrity gate and requires a parent device token (PIN-backed).

def _notify_member_lanes(member, title, body, path='/app'):
    """One member, all lanes: web push + HA companion notify."""
    try:
        base = (storage.get_settings().get('public_base_url') or '').rstrip('/')
        url = f"{base}{path}" if base else path
        send_push_to_member(member['id'], title, body, url)
        svc = member.get('notify_service')
        if svc:
            from services import ha_api
            svc_name = svc.split('.', 1)[1] if '.' in svc else svc
            payload = {"title": title, "message": body}
            if base:
                payload["data"] = {"url": url}
            ha_api.call_service('notify', svc_name, payload)
    except Exception as e:
        print(f"notify_member_lanes failed: {e}")

def _notify_chore_event(kind, chore, actor_member=None, extra=''):
    """Fan out chore lifecycle notifications in a background-safe way."""
    try:
        members = storage.get_all_members()
        if kind == 'posted':
            eligible = chore.get('eligible_member_ids') or []
            for m in members:
                if m.get('role') != 'child':
                    continue
                if eligible and m['id'] not in eligible:
                    continue
                _notify_member_lanes(m, 'New chore posted',
                                     f"{chore['title']} (+{chore.get('points', 0)} pts)",
                                     '/app?view=chores')
        elif kind == 'done':
            name = (actor_member or {}).get('name', 'Someone')
            for m in members:
                if m.get('role') == 'parent':
                    _notify_member_lanes(m, 'Chore ready to verify',
                                         f"{name} finished: {chore['title']}",
                                         '/app?view=chores')
        elif kind in ('verified', 'rejected'):
            claimant = storage.get_member(chore.get('claimed_by') or '')
            if claimant:
                if kind == 'verified':
                    body = f"{chore['title']} approved!" + (f" +{extra} points 🎉" if extra else '')
                else:
                    body = f"{chore['title']}: {extra or 'needs another pass'}"
                _notify_member_lanes(claimant,
                                     'Chore verified ✓' if kind == 'verified' else 'Chore needs a redo',
                                     body, '/app?view=chores')
    except Exception as e:
        print(f"chore notification failed: {e}")

class ChoreCreateRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    points: int = 10
    recurrence: str = 'once'
    eligible_member_ids: list = []

def _validate_chore_fields(req):
    if not (req.title or '').strip():
        raise HTTPException(status_code=400, detail="Title required")
    if not (0 <= int(req.points) <= 1000):
        raise HTTPException(status_code=400, detail="Points must be 0-1000")
    if req.recurrence not in ('once', 'daily', 'weekly', 'monthly'):
        raise HTTPException(status_code=400, detail="Invalid recurrence")

@app.get("/api/chores")
def list_chores():
    chores = storage.get_all_chores()
    members = {m['id']: m for m in storage.get_all_members()}
    for c in chores:
        claimant = members.get(c.get('claimed_by'))
        c['claimed_by_name'] = claimant.get('name') if claimant else None
        c['claimed_by_color'] = claimant.get('color_code') if claimant else None
    order = {'done': 0, 'open': 1, 'claimed': 2, 'verified': 3}
    chores.sort(key=lambda c: (order.get(c.get('state'), 9), -(c.get('points') or 0)))
    return chores

@app.post("/api/chores")
def create_chore(req: ChoreCreateRequest, background_tasks: BackgroundTasks):
    from models.schemas import Chore
    _validate_chore_fields(req)
    chore = Chore(title=req.title.strip(), description=req.description or '',
                  points=int(req.points), recurrence=req.recurrence,
                  eligible_member_ids=req.eligible_member_ids or []).model_dump()
    storage.add_chore(chore)
    background_tasks.add_task(_notify_chore_event, 'posted', chore)
    return chore

@app.put("/api/chores/{chore_id}")
def edit_chore(chore_id: str, req: ChoreCreateRequest):
    _validate_chore_fields(req)
    if not storage.update_chore(chore_id, {
            'title': req.title.strip(), 'description': req.description or '',
            'points': int(req.points), 'recurrence': req.recurrence,
            'eligible_member_ids': req.eligible_member_ids or []}):
        raise HTTPException(status_code=404, detail="Chore not found")
    return {"status": "updated"}

@app.delete("/api/chores/{chore_id}")
def remove_chore(chore_id: str):
    storage.delete_chore(chore_id)
    return {"status": "deleted"}

@app.post("/api/chores/{chore_id}/reopen")
def reopen_chore_endpoint(chore_id: str, background_tasks: BackgroundTasks):
    result = storage.reopen_chore(chore_id)
    if result == 'missing':
        raise HTTPException(status_code=404, detail="Chore not found")
    if result == 'not_reopenable':
        raise HTTPException(status_code=409,
                            detail="Only verified or claimed chores can be reopened — "
                                   "finished work awaiting verification should be verified or rejected in the app")
    chore = storage.get_chore(chore_id)
    background_tasks.add_task(_notify_chore_event, 'posted', chore)
    return chore

class ChoreMemberRequest(BaseModel):
    member_id: str

@app.post("/api/chores/{chore_id}/claim")
def claim_chore_endpoint(chore_id: str, req: ChoreMemberRequest):
    member = storage.get_member(req.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.get('role') == 'helper':
        raise HTTPException(status_code=403, detail="Helpers don't do family chores")
    chore = storage.get_chore(chore_id)
    if not chore:
        raise HTTPException(status_code=404, detail="Chore not found")
    eligible = chore.get('eligible_member_ids') or []
    if eligible and req.member_id not in eligible:
        raise HTTPException(status_code=403, detail="This chore isn't available to you")
    result = storage.claim_chore(chore_id, req.member_id)
    if result == 'not_open':
        raise HTTPException(status_code=409, detail="Already claimed")
    if result == 'cap':
        raise HTTPException(status_code=409,
                            detail=f"You already have {storage.CHORE_CLAIM_CAP} chores going — finish one first")
    if result != 'ok':
        raise HTTPException(status_code=404, detail="Chore not found")
    return storage.get_chore(chore_id)

@app.post("/api/chores/{chore_id}/unclaim")
def unclaim_chore_endpoint(chore_id: str, req: ChoreMemberRequest):
    if not storage.unclaim_chore(chore_id, req.member_id):
        raise HTTPException(status_code=409, detail="Not your claim (or not claimed)")
    return {"status": "released"}

@app.post("/api/chores/{chore_id}/done")
def chore_done_endpoint(chore_id: str, req: ChoreMemberRequest, background_tasks: BackgroundTasks):
    if not storage.mark_chore_done(chore_id, req.member_id):
        raise HTTPException(status_code=409, detail="Not your claim (or not in progress)")
    chore = storage.get_chore(chore_id)
    background_tasks.add_task(_notify_chore_event, 'done', chore,
                              storage.get_member(req.member_id))
    return chore

@app.post("/api/chores/{chore_id}/verify")
def verify_chore_endpoint(chore_id: str, background_tasks: BackgroundTasks,
                          x_member_token: Optional[str] = Header(None)):
    parent = require_parent_token(x_member_token)
    result = storage.verify_chore(chore_id, parent['id'])
    if result is None:
        raise HTTPException(status_code=409, detail="Chore is not awaiting verification")
    background_tasks.add_task(_notify_chore_event, 'verified', result['chore'],
                              parent, str(result['awarded'] or ''))
    return result

class ChoreRejectRequest(BaseModel):
    reason: Optional[str] = ""

@app.post("/api/chores/{chore_id}/reject")
def reject_chore_endpoint(chore_id: str, req: ChoreRejectRequest,
                          background_tasks: BackgroundTasks,
                          x_member_token: Optional[str] = Header(None)):
    parent = require_parent_token(x_member_token)
    chore = storage.reject_chore(chore_id, parent['id'], (req.reason or '').strip())
    if chore is None:
        raise HTTPException(status_code=409, detail="Chore is not awaiting verification")
    background_tasks.add_task(_notify_chore_event, 'rejected', chore, parent,
                              (req.reason or '').strip())
    return chore

@app.get("/api/points")
def all_points():
    return storage.get_all_point_balances()

class PointsAdjustRequest(BaseModel):
    member_id: str
    delta: Optional[int] = None    # relative change...
    set_to: Optional[int] = None   # ...or absolute target (exactly one)
    note: Optional[str] = ""

class PointsResetRequest(BaseModel):
    member_id: Optional[str] = None  # None = every child

@app.post("/api/points/adjust")
def adjust_points_endpoint(req: PointsAdjustRequest, background_tasks: BackgroundTasks):
    member = storage.get_member(req.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.get('role') != 'child':
        raise HTTPException(status_code=400, detail="Points are only tracked for children")
    if (req.delta is None) == (req.set_to is None):
        raise HTTPException(status_code=400, detail="Provide exactly one of delta or set_to")
    delta = int(req.delta) if req.delta is not None \
        else int(req.set_to) - storage.get_points_balance(req.member_id)
    if abs(delta) > 100000:
        raise HTTPException(status_code=400, detail="Adjustment too large")
    if delta == 0:
        return {'member_id': req.member_id, 'delta': 0,
                'balance': storage.get_points_balance(req.member_id)}
    balance = storage.adjust_points(req.member_id, delta, req.note or '')
    note = (req.note or '').strip()
    body = f"{'+' if delta > 0 else ''}{delta} points" + (f" — {note}" if note else '')
    background_tasks.add_task(_notify_member_lanes, member, 'Points adjusted',
                              body, '/app?view=chores')
    pending = sum(r['cost'] for r in storage.get_redemptions(req.member_id, 'pending'))
    return {'member_id': req.member_id, 'delta': delta, 'balance': balance,
            'pending_redemptions': pending}

@app.post("/api/points/reset")
def reset_points_endpoint(req: PointsResetRequest, background_tasks: BackgroundTasks):
    if req.member_id:
        member = storage.get_member(req.member_id)
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        if member.get('role') != 'child':
            raise HTTPException(status_code=400, detail="Points are only tracked for children")
    result = storage.reset_points(req.member_id)
    for entry in result['members']:
        if entry['cleared'] == 0:
            continue
        kid = storage.get_member(entry['member_id'])
        if kid:
            background_tasks.add_task(_notify_member_lanes, kid, 'Points reset',
                                      'Your points were reset by a parent',
                                      '/app?view=chores')
    return result

@app.get("/api/points/{member_id}")
def member_points(member_id: str, limit: int = 25):
    if not storage.get_member(member_id):
        raise HTTPException(status_code=404, detail="Member not found")
    return {
        'member_id': member_id,
        'balance': storage.get_points_balance(member_id),
        'ledger': storage.get_points_ledger(member_id, limit=limit),
    }

# --- Routines API (personal daily checklists; no points, streaks instead) ---

class RoutineRequest(BaseModel):
    member_id: str
    title: str
    time_of_day: Optional[str] = None
    days_of_week: list = []

def _validate_routine(req):
    if not (req.title or '').strip():
        raise HTTPException(status_code=400, detail="Title required")
    if req.time_of_day and not __import__('re').match(r'^\d{2}:\d{2}$', req.time_of_day):
        raise HTTPException(status_code=400, detail="time_of_day must be HH:MM")
    if any(not isinstance(d, int) or d < 0 or d > 6 for d in (req.days_of_week or [])):
        raise HTTPException(status_code=400, detail="days_of_week must be 0-6 (Mon-Sun)")

@app.get("/api/routines")
def list_routines(member_id: Optional[str] = None):
    routines = storage.get_routines(member_id)
    names = {m['id']: m.get('name') for m in storage.get_all_members()}
    for r in routines:
        r['member_name'] = names.get(r.get('member_id'))
    routines.sort(key=lambda r: (r.get('member_name') or '', r.get('time_of_day') or '99'))
    return routines

@app.post("/api/routines")
def create_routine(req: RoutineRequest):
    from models.schemas import RoutineItem
    _validate_routine(req)
    if not storage.get_member(req.member_id):
        raise HTTPException(status_code=404, detail="Member not found")
    item = RoutineItem(member_id=req.member_id, title=req.title.strip(),
                       time_of_day=req.time_of_day or None,
                       days_of_week=sorted(set(req.days_of_week or []))).model_dump()
    storage.add_routine(item)
    return item

@app.put("/api/routines/{routine_id}")
def edit_routine(routine_id: str, req: RoutineRequest):
    _validate_routine(req)
    if not storage.update_routine(routine_id, {
            'member_id': req.member_id, 'title': req.title.strip(),
            'time_of_day': req.time_of_day or None,
            'days_of_week': sorted(set(req.days_of_week or []))}):
        raise HTTPException(status_code=404, detail="Routine not found")
    return {"status": "updated"}

@app.delete("/api/routines/{routine_id}")
def remove_routine(routine_id: str):
    storage.delete_routine(routine_id)
    return {"status": "deleted"}

@app.get("/api/routines/day")
def routines_day(member_id: str, date: Optional[str] = None):
    import datetime as _dt
    date_str = date or _dt.date.today().isoformat()
    if not storage.get_member(member_id):
        raise HTTPException(status_code=404, detail="Member not found")
    return {
        'date': date_str,
        'items': storage.routines_for_day(member_id, date_str),
        'streak': storage.compute_streak(member_id),
    }

@app.get("/api/routines/streaks")
def routines_streaks():
    """Per-member streak summary for every member with routine items —
    feeds the routines page header chips and the kiosk streak board."""
    member_ids = {r['member_id'] for r in storage.get_routines()}
    out = []
    for m in storage.get_all_members():
        if m['id'] not in member_ids:
            continue
        out.append({
            'member_id': m['id'], 'name': m.get('name'),
            'color_code': m.get('color_code'), 'avatar': m.get('avatar'),
            'streak': storage.compute_streak(m['id']),
        })
    out.sort(key=lambda x: (-x['streak']['current'], x['name'] or ''))
    return out

class RoutineCheckRequest(BaseModel):
    member_id: str
    date: Optional[str] = None
    checked: bool = True

@app.post("/api/routines/{routine_id}/check")
def check_routine(routine_id: str, req: RoutineCheckRequest):
    import datetime as _dt
    date_str = req.date or _dt.date.today().isoformat()
    if not storage.set_routine_check(routine_id, req.member_id, date_str, req.checked):
        raise HTTPException(status_code=403, detail="Not your routine")
    return {'status': 'ok', 'streak': storage.compute_streak(req.member_id)}

# --- Rewards + redemptions API ---

class RewardRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    cost: int = 50

@app.get("/api/rewards")
def list_rewards():
    rewards = storage.get_rewards()
    rewards.sort(key=lambda r: r.get('cost', 0))
    return rewards

@app.post("/api/rewards")
def create_reward(req: RewardRequest):
    from models.schemas import Reward
    if not (req.title or '').strip():
        raise HTTPException(status_code=400, detail="Title required")
    if not (1 <= int(req.cost) <= 100000):
        raise HTTPException(status_code=400, detail="Cost must be positive")
    reward = Reward(title=req.title.strip(), description=req.description or '',
                    cost=int(req.cost)).model_dump()
    storage.add_reward(reward)
    return reward

@app.put("/api/rewards/{reward_id}")
def edit_reward(reward_id: str, req: RewardRequest):
    if not storage.update_reward(reward_id, {
            'title': req.title.strip(), 'description': req.description or '',
            'cost': int(req.cost)}):
        raise HTTPException(status_code=404, detail="Reward not found")
    return {"status": "updated"}

@app.delete("/api/rewards/{reward_id}")
def remove_reward(reward_id: str):
    storage.delete_reward(reward_id)
    return {"status": "deleted"}

@app.get("/api/redemptions")
def list_redemptions(member_id: Optional[str] = None, state: Optional[str] = None):
    rows = storage.get_redemptions(member_id, state)
    names = {m['id']: m.get('name') for m in storage.get_all_members()}
    for r in rows:
        r['member_name'] = names.get(r.get('member_id'))
    return rows

@app.post("/api/rewards/{reward_id}/redeem")
def redeem_reward(reward_id: str, req: ChoreMemberRequest, background_tasks: BackgroundTasks):
    member = storage.get_member(req.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.get('role') != 'child':
        raise HTTPException(status_code=403, detail="Only children redeem rewards")
    result = storage.request_redemption(reward_id, req.member_id)
    if result == 'missing':
        raise HTTPException(status_code=404, detail="Reward not found")
    if result == 'insufficient':
        raise HTTPException(status_code=409, detail="Not enough points (pending requests count)")
    reward = next((r for r in storage.get_rewards() if r['id'] == reward_id), {})

    def _notify_parents():
        for m in storage.get_all_members():
            if m.get('role') == 'parent':
                _notify_member_lanes(m, 'Reward request',
                                     f"{member.get('name')} wants: {reward.get('title')} ({reward.get('cost')} pts)",
                                     '/app?view=chores')
    background_tasks.add_task(_notify_parents)
    return {"status": "requested", "redemption_id": result}

class RedemptionDecision(BaseModel):
    approve: bool

@app.post("/api/redemptions/{redemption_id}/decide")
def decide_redemption_endpoint(redemption_id: str, req: RedemptionDecision,
                               background_tasks: BackgroundTasks,
                               x_member_token: Optional[str] = Header(None)):
    parent = require_parent_token(x_member_token)
    red = storage.decide_redemption(redemption_id, parent['id'], req.approve)
    if red is None:
        raise HTTPException(status_code=409, detail="Redemption is not pending")
    kid = storage.get_member(red['member_id'])
    if kid:
        body = f"{red['reward_title']} approved! -{red['cost']} points" if req.approve \
            else f"{red['reward_title']} — not this time"
        background_tasks.add_task(_notify_member_lanes, kid,
                                  'Reward approved 🎁' if req.approve else 'Reward request declined',
                                  body, '/app?view=chores')
    return red

# --- Sendspin phone-player relay ---
# The PWA registers as a real Music Assistant player (sendspin-js in the
# browser). Browsers on our https origin can't open MA's plain ws:// socket
# (mixed content), so this endpoint relays: browser <-wss same-origin->
# add-on <-ws LAN-> MA's Sendspin server (port 8927).

_MA_WS_CACHE = {'url': None}

def _ma_ws_candidates():
    out = []
    configured = (storage.get_settings().get('ma_server_url') or '').strip()
    if configured:
        url = configured
        if url.startswith(('http://', 'https://')):
            url = 'ws' + url[4:]
        if not url.startswith(('ws://', 'wss://')):
            url = f'ws://{url}'
        hostpart = url.split('://', 1)[1]
        if ':' not in hostpart.split('/', 1)[0]:
            url = url.replace(hostpart.split('/', 1)[0],
                              hostpart.split('/', 1)[0] + ':8927', 1)
        if '/sendspin' not in url:
            url = url.rstrip('/') + '/sendspin'
        out.append(url)
    # Official MA add-on hostname on HA's internal docker network
    out.append('ws://d5369777-music-assistant:8927/sendspin')
    # MA commonly runs on the HA host itself
    ha_base = os.environ.get('HA_BASE_URL', '') or storage.get_settings().get('ha_base_url', '')
    if ha_base:
        try:
            from urllib.parse import urlparse
            host = urlparse(ha_base).hostname
            if host:
                out.append(f'ws://{host}:8927/sendspin')
        except Exception:
            pass
    out.append('ws://homeassistant.local:8927/sendspin')
    seen = set()
    return [u for u in out if not (u in seen or seen.add(u))]

async def _resolve_ma_ws_url():
    import websockets as _ws
    if _MA_WS_CACHE['url']:
        return _MA_WS_CACHE['url']
    for candidate in _ma_ws_candidates():
        try:
            # Outer wait_for: open_timeout does not reliably bound stalled
            # DNS lookups (Windows mDNS/LLMNR) — without it a bad hostname
            # hangs the whole relay handshake.
            conn = await asyncio.wait_for(
                _ws.connect(candidate, open_timeout=4, max_size=None), timeout=5)
            await conn.close()
            print(f"[sendspin] MA server found at {candidate}")
            _MA_WS_CACHE['url'] = candidate
            return candidate
        except Exception as e:
            print(f"[sendspin] candidate {candidate} unreachable: {type(e).__name__}")
    return None

@app.websocket("/api/sendspin/ws")
async def sendspin_relay(websocket: WebSocket):
    import websockets as _ws
    await websocket.accept()
    url = await _resolve_ma_ws_url()
    if not url:
        await websocket.close(code=1011, reason="Music Assistant Sendspin server not found")
        return
    try:
        # Generous ping_timeout: heavy solver runs can stall the event loop
        # past the default 20s and needlessly kill healthy audio sessions.
        upstream = await _ws.connect(url, open_timeout=5, max_size=None,
                                     ping_interval=20, ping_timeout=60,
                                     close_timeout=5)
    except Exception as e:
        _MA_WS_CACHE['url'] = None  # stale cache; re-resolve next attempt
        print(f"[sendspin] upstream connect failed: {e}")
        await websocket.close(code=1011, reason="Could not reach Music Assistant")
        return

    async def pump_to_ma():
        while True:
            msg = await websocket.receive()
            if msg.get('type') == 'websocket.disconnect':
                break
            if msg.get('text') is not None:
                await upstream.send(msg['text'])
            elif msg.get('bytes') is not None:
                await upstream.send(msg['bytes'])

    async def pump_to_browser():
        async for message in upstream:
            if isinstance(message, str):
                await websocket.send_text(message)
            else:
                await websocket.send_bytes(message)

    tasks = [asyncio.create_task(pump_to_ma()),
             asyncio.create_task(pump_to_browser())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except Exception as e:
        print(f"[sendspin] relay error: {e}")
    finally:
        try:
            await upstream.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass

# --- Passenger day view API ---

@app.get("/api/members/{member_id}/day")
def member_day(member_id: str, date: Optional[str] = None):
    """A passenger-lens day: the member's events from the combined schedule
    cache (matched via their passenger record's calendar_ids/hashtags), each
    with the assigned driver resolved to a member and a drive status."""
    import datetime as _dt
    member = storage.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    date_str = date or _dt.date.today().isoformat()

    p_id = member.get('passenger_id')
    p_cals, p_tags = set(), set()
    if p_id:
        for p in storage.get_all_passengers():
            if p.get('id') == p_id:
                p_cals = set(p.get('calendar_ids') or [])
                p_tags = {t.lower() for t in (p.get('hashtags') or [])}
                break

    sched = storage.get_cached_schedule() or {}
    assignments = dict(sched.get('assignments', {}))
    assignments.update(sched.get('ghost_assignments', {}))
    matched_rules = sched.get('matched_rules', {}) or {}

    def _rule_bound(event_ids):
        # Rules can bind passengers to events the child's calendar doesn't
        # own (family-calendar events) — same resolution calendar.html uses.
        for eid in event_ids:
            for r in matched_rules.get(eid, []) or []:
                pax = r.get('passenger_ids') if isinstance(r, dict) else None
                if pax and str(p_id) in [str(x) for x in pax]:
                    return True
        return False

    status_by_event = {}
    for leg in storage.get_in_progress_drives():
        status_by_event.setdefault(_leg_event_id(leg), 'in_progress')
    for leg in storage.get_completed_drives():
        status_by_event.setdefault(_leg_event_id(leg), 'completed')

    driver_members = {}

    def _driver_member(driver_id):
        if not driver_id:
            return None
        if driver_id not in driver_members:
            m = storage.get_member_by_driver_id(driver_id)
            driver_members[driver_id] = {
                'member_id': m['id'], 'name': m.get('name'),
                'color_code': m.get('color_code'), 'avatar': m.get('avatar'),
                'role': m.get('role', 'adult'),
            } if m else None
        return driver_members[driver_id]

    # Collect matches, then collapse _dropoff/_pickup split legs into their
    # parent event (one card per real event, legs carry per-leg drivers).
    matched = []
    for ev in sched.get('events', []):
        if not str(ev.get('start', '')).startswith(date_str):
            continue
        if ev.get('event_type') == 'errand' or ev.get('trip_suppressed'):
            continue
        ev_id = str(ev.get('id', ''))
        parent_id = ev_id  # split-leg parent: suffix stripped, instance kept
        for suffix in ('_dropoff', '_pickup'):
            if parent_id.endswith(suffix):
                parent_id = parent_id[:-len(suffix)]
        rule_base = parent_id.split('_unrolled_')[0]
        cals = set(ev.get('calendar_ids') or [])
        title_l = (ev.get('title') or '').lower()
        if not (cals & p_cals) and not any(t in title_l for t in p_tags) \
                and not _rule_bound({ev_id, parent_id, rule_base}):
            continue
        matched.append((ev, ev_id, parent_id))

    def _ride(ev, ev_id, legs=None):
        return {
            'id': ev.get('id'),
            'title': ev.get('title'),
            'event_type': ev.get('event_type', 'standard'),
            'start': ev.get('start'),
            'end': ev.get('end'),
            'location': ev.get('location'),
            'driver': _driver_member(assignments.get(ev_id)),
            'status': status_by_event.get(ev_id),
            'legs': legs or [],
        }

    groups = {}
    for item in matched:
        groups.setdefault(item[2], []).append(item)

    rides = []
    for parent_id, items in groups.items():
        base = next((it for it in items if it[1] == parent_id), None)
        variants = [it for it in items if it[1] != parent_id]
        if base is None:
            rides.extend(_ride(ev, ev_id) for ev, ev_id, _p in items)
            continue
        legs = []
        for ev, ev_id, _p in sorted(variants, key=lambda it: it[0].get('start') or ''):
            legs.append({
                'type': 'dropoff' if ev_id.endswith('_dropoff') else 'pickup',
                'start': ev.get('start'),
                'driver': _driver_member(assignments.get(ev_id)),
                'status': status_by_event.get(ev_id),
            })
        ride = _ride(base[0], base[1], legs)
        if any(l['status'] == 'in_progress' for l in legs):
            ride['status'] = 'in_progress'
        elif legs and all(l['status'] == 'completed' for l in legs):
            ride['status'] = 'completed'
        rides.append(ride)
    rides.sort(key=lambda r: r.get('start') or '')
    return {
        'member_id': member_id,
        'name': member.get('name'),
        'date': date_str,
        'rides': rides,
    }

# --- Family map API ---

def _leg_event_id(leg_id):
    """Collapse a drive-leg id (init_{ev}, route_{ev}_1..3, final_{ev}) back
    to its event id."""
    import re as _re
    s = str(leg_id)
    s = _re.sub(r'^(init_|route_|final_)', '', s)
    s = _re.sub(r'_[123]$', '', s)
    return s

@app.get("/api/family/locations")
def family_locations():
    """Every member with map-relevant data: HA person state/coords (absent
    for router-based trackers -> zone chip only) plus 'driving' context from
    in-progress drive legs joined to the cached schedule's assignments."""
    from services import ha_api
    driving_by_driver = {}
    try:
        sched = storage.get_cached_schedule() or {}
        events_by_id = {e.get('id'): e for e in sched.get('events', [])}
        assignments = dict(sched.get('assignments', {}))
        assignments.update(sched.get('ghost_assignments', {}))
        for leg in storage.get_in_progress_drives():
            ev_id = _leg_event_id(leg)
            ev = events_by_id.get(ev_id)
            drv = assignments.get(ev_id)
            if ev and drv and drv not in driving_by_driver:
                driving_by_driver[drv] = ev.get('title') or 'a drive'
    except Exception as e:
        print(f"family_locations: en-route enrichment failed: {e}")

    out = []
    for m in storage.get_all_members():
        if m.get('role') == 'helper':
            continue  # outside the family bubble; no HA person entity anyway
        entry = {
            'member_id': m['id'],
            'name': m.get('name'),
            'color_code': m.get('color_code'),
            'avatar': m.get('avatar'),
            'is_child': m.get('is_child', False),
            'state': None,
            'latitude': None,
            'longitude': None,
            'gps_accuracy': None,
            'last_updated': None,
            'driving': None,
        }
        if m.get('driver_id') and m['driver_id'] in driving_by_driver:
            entry['driving'] = {'leg_title': driving_by_driver[m['driver_id']]}
        ent = m.get('ha_person_entity')
        if ent:
            s = ha_api.get_state(ent)
            if s:
                attrs = s.get('attributes') or {}
                entry.update(
                    state=s.get('state'),
                    latitude=attrs.get('latitude'),
                    longitude=attrs.get('longitude'),
                    gps_accuracy=attrs.get('gps_accuracy'),
                    last_updated=s.get('last_updated'),
                )
        out.append(entry)
    return out

@app.get("/api/channels")
def list_channels(member_id: str):
    channels = storage.get_channels_for_member(member_id)
    unread = storage.get_unread_counts(member_id)
    for c in channels:
        msgs = storage.get_channel_messages(c['id'], limit=1)
        c['last_message'] = msgs[-1] if msgs else None
        c['unread'] = unread.get(c['id'], 0)
    # Channels with no messages yet don't get listed (except the family hub):
    # Discuss/Message get-or-create a channel the moment the thread is opened,
    # and an untouched thread must not clutter the whole household's list.
    # It appears for everyone once the first message is posted.
    channels = [c for c in channels if c.get('kind') == 'family' or c['last_message']]
    # family channel pinned first, then most recent activity
    channels.sort(key=lambda c: (
        0 if c.get('kind') == 'family' else 1,
        -((c.get('last_message') or {}).get('ts') or c.get('created_at', 0)),
    ))
    return channels

class DmChannelRequest(BaseModel):
    member_id: str
    other_member_id: str

@app.post("/api/channels/dm")
def create_dm_channel(req: DmChannelRequest):
    if req.member_id == req.other_member_id:
        raise HTTPException(status_code=400, detail="Cannot DM yourself")
    pair = []
    for mid in (req.member_id, req.other_member_id):
        member = storage.get_member(mid)
        if not member:
            raise HTTPException(status_code=404, detail=f"Member {mid} not found")
        pair.append(member)
    # Helpers (external drivers/nannies) may only DM parents.
    for a, b in ((pair[0], pair[1]), (pair[1], pair[0])):
        if a.get('role') == 'helper' and b.get('role') != 'parent':
            raise HTTPException(status_code=403,
                                detail="Helpers can only exchange messages with parents")
    return storage.get_or_create_dm(req.member_id, req.other_member_id)

class EventChannelRequest(BaseModel):
    event_id: str
    title: str = ""
    event_end: Optional[str] = None

@app.post("/api/channels/event")
def create_event_channel(req: EventChannelRequest):
    return storage.get_or_create_event_channel(req.event_id, req.title, req.event_end)

@app.get("/api/channels/{channel_id}/messages")
def get_messages(channel_id: str, after_ts: Optional[float] = None, limit: int = 50):
    if not storage.get_channel(channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    return storage.get_channel_messages(channel_id, after_ts=after_ts, limit=limit)

class SendMessageRequest(BaseModel):
    sender_member_id: str
    body: str

@app.post("/api/channels/{channel_id}/messages")
def send_message(channel_id: str, req: SendMessageRequest, background_tasks: BackgroundTasks):
    channel = storage.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if channel.get('archived'):
        raise HTTPException(status_code=409, detail="Channel is archived")
    body = (req.body or '').strip()
    if not body:
        raise HTTPException(status_code=400, detail="Empty message")
    sender = storage.get_member(req.sender_member_id)
    if not sender:
        raise HTTPException(status_code=404, detail="Sender member not found")
    if channel.get('kind') == 'dm' and req.sender_member_id not in (channel.get('member_ids') or []):
        raise HTTPException(status_code=403, detail="Not a member of this DM")
    if sender.get('role') == 'helper' and channel.get('kind') != 'dm':
        raise HTTPException(status_code=403, detail="Helpers can only post in their DMs")

    from models.schemas import ChatMessage
    message = ChatMessage(channel_id=channel_id,
                          sender_member_id=req.sender_member_id,
                          body=body).model_dump()
    storage.add_chat_message(message)
    # Sender has obviously read their own message.
    storage.set_last_read(channel_id, req.sender_member_id, message['ts'])
    recipients = channel.get('member_ids') if channel.get('kind') == 'dm' else None
    _push_message_event(channel_id, recipients)
    background_tasks.add_task(_fanout_message_notifications, channel, message)
    return message

class ChannelReadRequest(BaseModel):
    member_id: str
    ts: Optional[float] = None

@app.post("/api/channels/{channel_id}/read")
def mark_channel_read(channel_id: str, req: ChannelReadRequest):
    storage.set_last_read(channel_id, req.member_id, req.ts or time.time())
    return {"status": "ok"}

@app.get("/api/messages/stream")
async def stream_messages(member_id: str):
    """Addressed SSE: yields {'channel_id'} whenever a message lands in a
    channel this member can see. Clients refetch just that channel."""
    import json as _json

    async def event_generator():
        last_seq = MESSAGE_EVENTS[-1]['seq'] if MESSAGE_EVENTS else 0
        last_ping = time.time()
        try:
            while True:
                await asyncio.sleep(1)
                now = time.time()
                sent = False
                for ev in list(MESSAGE_EVENTS):
                    if ev['seq'] <= last_seq:
                        continue
                    last_seq = ev['seq']
                    if ev['recipients'] is None or member_id in ev['recipients']:
                        yield f"data: {_json.dumps({'channel_id': ev['channel_id']})}\n\n"
                        sent = True
                if sent:
                    last_ping = now
                elif now - last_ping > 15:
                    yield ": ping\n\n"
                    last_ping = now
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")

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
                # WAL sidecars are meaningless without a matching main file
                if file.endswith(('-wal', '-shm')) or file.endswith('.migrating'):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, data_dir)
                if file.endswith('.sqlite3'):
                    # zipping a live WAL database copies a torn state; use the
                    # SQLite backup API for a consistent snapshot instead
                    import sqlite3
                    import tempfile
                    tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
                    tmp.close()
                    try:
                        src = sqlite3.connect(file_path)
                        dst = sqlite3.connect(tmp.name)
                        with dst:
                            src.backup(dst)
                        dst.close()
                        src.close()
                        zip_file.write(tmp.name, arcname)
                    finally:
                        os.unlink(tmp.name)
                else:
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
            elif ctype == 'day_of_week':
                if r.get('valid_days_of_week') and not errand_dict.get('valid_days_of_week'): errand_dict['valid_days_of_week'] = r['valid_days_of_week']
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

class OverrideCheckPayload(BaseModel):
    event_id: str
    driver_id: str

@app.post("/api/overrides/check")
def check_override_conflicts(payload: OverrideCheckPayload):
    """Dry-run: reasons the solver would normally refuse this (event, driver)
    pair. Informational only — the override still wins if created."""
    from models.schemas import Event as EventModel
    import datetime as _dt
    cache = storage.get_cached_schedule()
    ev_dict = next((e for e in cache.get("events", []) if e.get("id") == payload.event_id), None)
    d_dict = next((d for d in storage.get_all_drivers() if d.get("id") == payload.driver_id), None)
    if not ev_dict or not d_dict:
        return {"conflicts": []}
    try:
        event = EventModel(**ev_dict)
        d_dict.setdefault('group', 'primary'); d_dict.setdefault('priority_index', 1); d_dict.setdefault('calendar_ids', [])
        driver = Driver(**d_dict)
    except Exception:
        return {"conflicts": []}

    settings = storage.get_settings()
    enable_ai = settings.get("enable_ai_rules", True)
    enable_std = settings.get("enable_standard_rules", True)
    rules = []
    for r in storage.get_all_rules():
        try:
            rule_obj = Rule(**r)
        except Exception:
            continue
        if not rule_obj.is_enabled: continue
        if rule_obj.is_ai_generated and not enable_ai: continue
        if not rule_obj.is_ai_generated and not enable_std: continue
        rules.append(rule_obj)
    passengers = [Passenger(**p) for p in storage.get_all_passengers()]

    trips = []
    for tm in cache.get("trip_metadata", []):
        try:
            trips.append({**tm,
                          "start": _dt.datetime.fromisoformat(tm["start"]),
                          "end": _dt.datetime.fromisoformat(tm["end"]),
                          "entities": set(tm.get("entities") or [])})
        except Exception:
            continue

    events_by_id = {e.get("id"): e for e in cache.get("events", [])}
    driver_events = []
    for ev_id in cache.get("driver_events", {}).get(payload.driver_id, []):
        de = events_by_id.get(ev_id)
        if de:
            try:
                driver_events.append(EventModel(**de))
            except Exception:
                pass

    conflicts = matcher.explain_assignment_conflicts(
        event, driver, rules=rules, passengers=passengers,
        trip_metadata=trips, driver_events=driver_events)
    return {"conflicts": conflicts}

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
def update_event_config(google_id: str, config_data: dict):
    # Persist before responding: the write is a fast local upsert, and a client
    # that re-reads on our "updated" must not race ahead of it. Only the solve
    # is slow, and trigger_background_refresh does not block.
    storage.set_event_config(google_id, config_data)
    trigger_background_refresh()
    return {"status": "updated"}

@app.delete("/api/events/config/{google_id}")
def delete_event_config(google_id: str):
    storage.delete_event_config(google_id)
    trigger_background_refresh()
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
    # MERGE, don't replace: clients send only the fields they manage (the
    # config page doesn't know about intake creds; /intake doesn't know about
    # solver toggles). exclude_unset keeps model defaults from clobbering
    # stored values a client never sent — a blind replace here silently wiped
    # intake mailbox credentials on every config-page save.
    incoming = settings.model_dump(exclude_unset=True)
    current = storage.get_settings() or {}
    current.update(incoming)
    storage.update_settings(current)
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "updated"}

class ChatMessagePayload(BaseModel):
    message: str
    source: Optional[str] = "admin"
    driver_id: Optional[str] = None
    context: Optional[dict] = None
    conversation_id: Optional[str] = None

@app.post("/api/chat")
def handle_chat(payload: ChatMessagePayload, background_tasks: BackgroundTasks):
    from services.agent_router import process_agent_request
    from services.llm import auto_name_conversation
    import time
    
    try:
        is_first = False
        if payload.conversation_id:
            conv = storage.get_conversation(payload.conversation_id)
            if conv and len(conv.get("messages", [])) == 0:
                is_first = True
        
        import threading
        if is_first and payload.conversation_id:
            threading.Thread(target=auto_name_conversation, args=(payload.conversation_id, payload.message)).start()

        conv_history = []
        if payload.conversation_id:
            conv = storage.get_conversation(payload.conversation_id)
            if conv:
                conv_history = conv.get("messages", [])
                
            storage.add_message_to_conversation(payload.conversation_id, {'role': 'user', 'content': payload.message, 'timestamp': time.time()})

        res = process_agent_request(payload.message, context=payload.context, history=conv_history,
                                    source=payload.source or "admin", driver_id=payload.driver_id)
        reply = res.get("message", "I did not understand that.")
        target_id = res.get("target_element_id")
        
        if target_id:
            global LAST_UPDATE_TIME
            LAST_UPDATE_TIME = time.time()

        # Same as /api/v2/converse: agent overrides need a re-solve to show up.
        if res.get("schedule_dirty"):
            background_tasks.add_task(trigger_background_refresh)

        if payload.conversation_id:
            storage.add_message_to_conversation(payload.conversation_id, {'role': 'assistant', 'content': reply, 'timestamp': time.time()})
            
        if res.get("ui_action") == "generate_massive_trip":
            trip_id = None
            if payload.context:
                import urllib.parse
                if "search" in payload.context and "event_id=" in payload.context["search"]:
                    qs = urllib.parse.parse_qs(payload.context["search"].lstrip("?"))
                    if "event_id" in qs:
                        trip_id = qs["event_id"][0]
                elif "pathname" in payload.context and "/trip/" in payload.context["pathname"]:
                    trip_id = payload.context["pathname"].split("/trip/")[-1].split("/")[0]
                    
            if trip_id:
                def _bg_generate(t_id, user_prompt, conv_id):
                    try:
                        from models.schemas import TripMetadata
                        from services.trip_planner import generate_trip_plan
                        meta_dict = storage.get_trip_metadata(t_id)
                        if not meta_dict:
                            logger.error(f"Could not find trip {t_id}")
                            raise Exception("Trip not found")
                            
                        trip = TripMetadata(**meta_dict)
                        duration = trip.draft_duration_nights or 7
                        
                        warning, pois, accs, flights = generate_trip_plan(trip, user_prompt, duration)
                        
                        if 'pois' not in meta_dict: meta_dict['pois'] = []
                        if 'accommodations' not in meta_dict: meta_dict['accommodations'] = []
                        if 'flights' not in meta_dict: meta_dict['flights'] = []

                        existing_poi_names = {p.get('name', '').lower() for p in meta_dict['pois']}
                        for poi in pois:
                            if poi.name.lower() not in existing_poi_names:
                                meta_dict['pois'].append(poi.model_dump() if hasattr(poi, 'model_dump') else poi.dict())
                                existing_poi_names.add(poi.name.lower())

                        existing_acc_names = {a.get('name', '').lower() for a in meta_dict['accommodations']}
                        for acc in accs:
                            if acc.name.lower() not in existing_acc_names:
                                meta_dict['accommodations'].append(acc.model_dump() if hasattr(acc, 'model_dump') else acc.dict())
                                existing_acc_names.add(acc.name.lower())

                        # Flights were generated but previously dropped on the floor here —
                        # persist them with the same origin-destination-airline dedup key
                        # used by the /generate_pois endpoint.
                        existing_flight_keys = {f"{f.get('origin')}-{f.get('destination')}-{f.get('airline')}" for f in meta_dict['flights']}
                        for flight in flights:
                            key = f"{flight.origin}-{flight.destination}-{flight.airline}"
                            if key not in existing_flight_keys:
                                meta_dict['flights'].append(flight.model_dump() if hasattr(flight, 'model_dump') else flight.dict())
                                existing_flight_keys.add(key)

                        storage.set_trip_metadata(t_id, meta_dict)

                        msg = f"I've finished planning your trip! I generated {len(pois)} points of interest, {len(accs)} accommodations, and {len(flights)} flights. {warning or ''}"
                        if conv_id:
                            storage.add_message_to_conversation(conv_id, {'role': 'assistant', 'content': msg, 'timestamp': time.time()})
                        
                        CHAT_EVENTS.append({
                            "reply": msg,
                            "ui_action": "reload"
                        })
                        
                        global LAST_UPDATE_TIME
                        LAST_UPDATE_TIME = time.time()
                    except Exception as e:
                        logger.error(f"Background trip gen error: {e}")
                        CHAT_EVENTS.append({
                            "reply": f"⚠️ An error occurred while generating your trip: {str(e)}",
                            "ui_action": "reload"
                        })
                        
                background_tasks.add_task(_bg_generate, trip_id, payload.message, payload.conversation_id)
            
        return {"reply": reply, "target_element_id": target_id, "ui_action": res.get("ui_action"), "target_driver_id": res.get("target_driver_id")}
    except Exception as e:
        import traceback
        logger.error(f"Error in chat loop: {traceback.format_exc()}")
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.get("/api/chat/history")
def get_chat_history(conversation_id: str = None):
    if not conversation_id:
        return {"history": []}
    conv = storage.get_conversation(conversation_id)
    return {"history": conv.get("messages", []) if conv else []}

@app.delete("/api/chat/history")
def clear_chat_history():
    storage.clear_chat_history()
    return {"status": "cleared"}

class CreateConversationPayload(BaseModel):
    type: str = "general"
    mode: str = "standard"
    title: str = "New Conversation"
    context_id: Optional[str] = None

@app.get("/api/chat/conversations")
def get_conversations():
    return {"conversations": storage.get_all_conversations()}

@app.post("/api/chat/conversations")
def create_conversation(payload: CreateConversationPayload):
    conv_data = payload.model_dump() if hasattr(payload, 'model_dump') else payload.dict()
    import uuid, time
    conv_data['id'] = uuid.uuid4().hex
    conv_data['messages'] = []
    conv_data['created_at'] = time.time()
    conv_data['updated_at'] = time.time()
    conv_id = storage.create_conversation(conv_data)
    return {"id": conv_id, "conversation": conv_data}

@app.delete("/api/chat/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    storage.delete_conversation(conv_id)
    return {"status": "deleted"}

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
        },
        "map_loads": {
            "monthly": storage.get_mapbox_usage(current_month, 'map_loads'),
            "rolling_24h": storage.get_rolling_usage('map_loads', 86400),
            "rpm": storage.get_rolling_usage('map_loads', 60),
            "limit": maps.get_map_option('mapbox_map_loads_limit', 45000),
            "disabled": not maps.get_map_option('enable_mapbox_map_loads', True) or maps.get_map_option('disable_mapbox', False)
        },
        "has_key": bool(maps.get_mapbox_api_key())
    }
    
    return {"status": "success", "month": current_month, "stats": stats}

# --- Telemetry API ---
@app.post("/api/telemetry/mapbox_map_load")
def track_mapbox_map_load():
    import datetime
    current_month = datetime.datetime.now().strftime("%Y-%m")
    storage.increment_mapbox_usage(current_month, 'map_loads')
    return {"status": "recorded"}

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
def update_event_details(payload: EventDetailsUpdate, background_tasks: BackgroundTasks):
    try:
        details = payload.model_dump(exclude_unset=True) if hasattr(payload, 'model_dump') else payload.dict(exclude_unset=True)
        # remove source_event_ids from details
        details.pop('source_event_ids', None)

        # Deferred because this is a Google Calendar round trip, not a local
        # write - too slow to hold the request open. BackgroundTasks runs it
        # after the response inside FastAPI's bounded threadpool, so a burst of
        # edits cannot spawn unbounded threads.
        def _apply_update():
            try:
                calendar.update_event_details(payload.source_event_ids, details)
                trigger_background_refresh()
            except Exception as e:
                logger.error(f"Error applying calendar update: {e}", exc_info=True)

        background_tasks.add_task(_apply_update)
        return {"status": "updating_in_background"}
    except Exception as e:
        return {"error": str(e)}

# --- Maps API ---
@app.get("/api/maps/route_info")
def get_route_info(origin: str, destination: str):
    mins = maps.get_travel_time_minutes(origin, destination)
    return {"duration": f"{mins * 60}s", "distanceMeters": mins * 1000}  # Mock distance

@app.get("/api/maps/route_geometry")
def get_route_geometry_api(
    origin: str, 
    destination: str, 
    profile: str = "driving",
    origin_lat: Optional[float] = None,
    origin_lng: Optional[float] = None,
    dest_lat: Optional[float] = None,
    dest_lng: Optional[float] = None
):
    result = maps.get_route_geometry(origin, destination, profile, origin_lat, origin_lng, dest_lat, dest_lng)
    if result:
        return result
    return {"error": "Could not fetch route"}

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

@app.get("/api/places/geocode")
def get_places_geocode(address: str):
    result = maps.geocode_address(address)
    if result:
        return {"lat": result[0], "lng": result[1]}
    from fastapi import HTTPException
    raise HTTPException(status_code=400, detail="Failed to geocode address")

from functools import lru_cache

@lru_cache(maxsize=128)
def _fetch_wikidata_image(wikidata_id: str) -> str:
    import urllib.parse
    import requests
    import hashlib
    headers = {"User-Agent": "ChauffeurScheduleAssistant/1.0 (https://github.com/EpicJeff/Chauffeur-Scheduling-Assistant; jeff@example.com)"}
    try:
        url = f"https://www.wikidata.org/w/api.php?action=wbgetclaims&entity={wikidata_id}&property=P18&format=json"
        res = requests.get(url, headers=headers, timeout=3)
        if res.ok:
            data = res.json()
            claims = data.get('claims', {}).get('P18', [])
            if claims:
                filename = claims[0].get('mainsnak', {}).get('datavalue', {}).get('value')
                if filename:
                    # Construct wikimedia commons URL using Special:FilePath
                    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(filename)}?width=800"
    except Exception as e:
        print(f"Wikidata Image Fetch Error: {e}")
    return None

def _fetch_wikipedia_image_url(query: str) -> str:
    import urllib.parse
    import requests
    headers = {"User-Agent": "ChauffeurScheduleAssistant/1.0 (https://github.com/EpicJeff/Chauffeur-Scheduling-Assistant; jeff@example.com)"}
    try:
        search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json"
        res = requests.get(search_url, headers=headers, timeout=3)
        if res.ok:
            data = res.json()
            search_results = data.get('query', {}).get('search', [])
            if search_results:
                page_id = search_results[0]['pageid']
                img_url = f"https://en.wikipedia.org/w/api.php?action=query&pageids={page_id}&prop=pageimages&format=json&pithumbsize=1000"
                img_res = requests.get(img_url, headers=headers, timeout=3)
                if img_res.ok:
                    img_data = img_res.json()
                    pages = img_data.get('query', {}).get('pages', {})
                    if str(page_id) in pages:
                        thumbnail = pages[str(page_id)].get('thumbnail')
                        if thumbnail and thumbnail.get('source'):
                            return thumbnail['source']
    except Exception as e:
        print(f"Wikipedia Image Fetch Error: {e}")
    return None

def _fetch_unsplash_url(query: str, api_key: str, wikidata_id: str = None) -> str:
    import urllib.parse
    import requests
    import hashlib
    
    # Generate a deterministic placeholder based on the query name
    hash_val = int(hashlib.md5(query.encode('utf-8')).hexdigest(), 16) if query else 0
    placeholder_idx = (hash_val % 3) + 1
    fallback_url = f"/static/placeholders/{placeholder_idx}.png"

    if not query:
        return fallback_url
        
    if 'paris' in query.lower():
        fallback_url = "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?q=80&w=1920&auto=format&fit=crop"
    elif 'tokyo' in query.lower():
        fallback_url = "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?q=80&w=1920&auto=format&fit=crop"
    elif 'london' in query.lower():
        fallback_url = "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?q=80&w=1920&auto=format&fit=crop"

    # 1. Try Wikidata First if we have a wikidata_id
    if wikidata_id:
        wiki_img = _fetch_wikidata_image(wikidata_id)
        if wiki_img:
            return wiki_img

    # 2. Try Wikipedia Search as a fallback
    wiki_img = _fetch_wikipedia_image_url(query)
    if wiki_img:
        return wiki_img

    # 3. Try Unsplash API if key is present
    if not api_key:
        print("Unsplash API: No API key found in options")
    else:
        encoded_query = urllib.parse.quote(query)
        try:
            api_url = f"https://api.unsplash.com/search/photos?query={encoded_query}&orientation=landscape&per_page=1"
            res = requests.get(
                api_url,
                headers={"Authorization": f"Client-ID {api_key}"},
                timeout=5
            )
            if res.ok:
                data = res.json()
                if data.get("results") and len(data["results"]) > 0:
                    return data["results"][0]["urls"]["regular"]
        except Exception as e:
            print(f"Unsplash API Error: {e}")

    # 4. Fallback
    return fallback_url

@app.get("/api/unsplash/background")
def get_unsplash_background(query: str, wikidata_id: str = None):
    # Uses official Unsplash API if a key is provided in Addon Config
    api_key = maps.get_map_option('unsplash_api_key', None)
    
    url = _fetch_unsplash_url(query, api_key, wikidata_id)
        
    return RedirectResponse(url=url, headers={"Cache-Control": "public, max-age=86400"})

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
    """Serializes schedule refreshes and coalesces repeats.

    A refresh is a full multi-day CP-SAT solve. Running several at once is
    never useful - they duplicate each other's work and, being CPU-bound,
    saturate the GIL and starve the HTTP handlers. So at most one refresh runs
    at a time, and requests arriving during a run collapse into a single queued
    re-run with the newest arguments (latest-wins), rather than a backlog.
    """

    def __init__(self):
        self.lock = threading.RLock()
        # Held for the duration of a pass, by background AND synchronous
        # callers alike, so the two can never overlap.
        self.run_lock = threading.Lock()
        self.is_running = False
        self.pending_refresh = False
        self.pending_args = None
        self.current_args = None
        self.runner_thread = None
        self.solving_dates = set()

    def try_start(self, args):
        """Claim the background runner slot.

        Returns True if the caller should spawn the runner. Returns False if a
        run is already in flight, in which case args are queued and the running
        pass is asked to abort and restart with them.
        """
        with self.lock:
            if self.is_running:
                self.pending_refresh = True
                self.pending_args = args
                return False
            self.is_running = True
            self.current_args = args
            self.pending_refresh = False
            self.pending_args = None
            return True

    def take_pending(self):
        """Finish a pass: return queued args to run next, or None.

        Returning None releases the runner slot, so the caller must stop.
        """
        with self.lock:
            if self.pending_refresh:
                self.current_args = self.pending_args
                self.pending_refresh = False
                self.pending_args = None
                return self.current_args
            self.is_running = False
            self.current_args = None
            self.runner_thread = None
            return None

    def abandon(self):
        """Release the slot after an unexpected failure, so refreshes can resume."""
        with self.lock:
            self.is_running = False
            self.pending_refresh = False
            self.pending_args = None
            self.current_args = None
            self.runner_thread = None

    def should_abort(self):
        """True only for the background runner once newer args have been queued.

        Synchronous callers are never aborted: they have a caller waiting on the
        result, and returning an abort to them would surface as a failure.
        """
        with self.lock:
            return (self.pending_refresh
                    and self.runner_thread is threading.current_thread())

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
    if schedule_coordinator.should_abort():
        raise AbortRefreshException()

def trigger_background_refresh(start_date_str=None, end_date_str=None, force_refresh=False, draft=False):
    """Request a refresh without blocking the caller.

    Returns immediately. If a refresh is already running this coalesces into
    it rather than starting a second one, so a burst of edits costs one re-run,
    not one per edit.
    """
    args = (start_date_str, end_date_str, force_refresh, draft)
    if not schedule_coordinator.try_start(args):
        return

    def _run():
        held = True
        try:
            current = args
            while current is not None:
                try:
                    refresh_schedule_logic(*current)
                except AbortRefreshException:
                    logger.info("Schedule refresh superseded; restarting with newer request")
                    # The aborted pass left days marked in-flight; the restart
                    # re-marks whatever it actually solves.
                    schedule_coordinator.clear_solving_dates()
                except Exception as e:
                    logger.error(f"Error in background schedule run: {e}", exc_info=True)
                    schedule_coordinator.clear_solving_dates()
                current = schedule_coordinator.take_pending()
            held = False
            # The whole run (all progressively solved days, including any
            # coalesced re-requests) is done — send the batched notifications.
            try:
                flush_assignment_notifications()
            except Exception as e:
                logger.error(f"Assignment-change notification flush failed: {e}", exc_info=True)
        finally:
            # take_pending() releases the slot by returning None; anything else
            # leaving this thread must release it too, or refreshes wedge
            # permanently with is_running stuck True.
            if held:
                schedule_coordinator.abandon()

    t = threading.Thread(target=_run, daemon=True)
    schedule_coordinator.runner_thread = t
    t.start()

import threading

def refresh_schedule_logic(start_date_str=None, end_date_str=None, force_refresh=False, draft=False):
    try:
        # The single serialization point. Every caller passes through here -
        # the background runner and the synchronous endpoints alike - so two
        # solves can never overlap regardless of how they were requested.
        with schedule_coordinator.run_lock:
            res = _refresh_schedule_logic_impl(start_date_str, end_date_str, force_refresh, draft)
        global LAST_UPDATE_TIME
        LAST_UPDATE_TIME = time.time()
        return res
    except AbortRefreshException:
        # Not a failure: a newer request superseded this pass. The background
        # runner catches this and restarts with the newer arguments.
        raise
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
    
    # The build horizon is deliberately NOT days_to_show: that setting only
    # controls how much the kiosk renders. Days are solved progressively and
    # cached per-day, so a longer horizon costs nothing on refreshes where the
    # events for a day are unchanged.
    days_to_fetch = int(settings.get('days_to_build', 30))

    
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

    with storage.db_lock:
        all_event_configs_docs = storage.event_configs_table.all()
    configs_by_google_id = {c['google_id']: c for c in all_event_configs_docs if 'google_id' in c}

    for e in all_fetched_events:
        original_calendar_ids = list(e.calendar_ids)
        e.original_calendar_ids = original_calendar_ids
        
        # 1. Fetch Event Config
        config = None
        for src_id in getattr(e, 'source_event_ids', [e.id]):
            parts = src_id.split('::')
            google_id = parts[-1] if len(parts) > 1 else src_id
            config = configs_by_google_id.get(google_id)
            if config:
                e.app_config = config
                break
                
        # Fallback to recurring series config
        if not config and getattr(e, 'recurring_event_id', None):
            config = configs_by_google_id.get(e.recurring_event_id)
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
            
            # Fetch explicitly configured attendees from trip metadata
            tm_meta = storage.get_trip_metadata(e.id)
            if tm_meta and tm_meta.get('attendees'):
                for attendee in tm_meta['attendees']:
                    applicable_entities.add(attendee)
            
            # Use triaged passenger assignments (legacy fallback)
            if hasattr(e, 'calendar_ids') and e.calendar_ids:
                for cid in e.calendar_ids:
                    applicable_entities.add(f"passenger_{cid}")
                    
            # Use triaged driver assignments (legacy fallback)
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
                "title": e.title,
                "location": e.location,
                "entities": applicable_entities,
                "all_day": e.all_day
            })
            
    for tm in trip_metadata:
        meta = storage.get_trip_metadata(tm['id'])
        if not meta or not meta.get('pois'):
            continue
            
        # The trip itinerary's scheduled state is owned SOLELY by the trip page's
        # CP-SAT scheduler (schedule_pois_bulk), triggered explicitly by the user.
        # The daily family solver must NOT wipe or reschedule it — doing so clobbered
        # the user's itinerary (and dropped calendar-backed reservations) on every
        # background refresh. Already-scheduled POIs are left untouched below.
        for poi in meta['pois']:
            if poi.get('is_scheduled') and (not draft and not start_date_str and not end_date_str):
                continue
                
            starts_on_ts = tm['start'].timestamp()
            window_days = (tm['end'].date() - tm['start'].date()).days + 1
            
            occurrences = poi.get('occurrences', 1)
            for i in range(occurrences):
                errand_id = f"{tm['id']}_poi_{poi['id']}" if occurrences == 1 else f"{tm['id']}_poi_{poi['id']}_occ_{i}"
                errands.append({
                    'id': errand_id,
                    'doc_id': -1,
                    'title': poi['name'] if occurrences == 1 else f"{poi['name']} (Day {i+1})",
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
                # Everyone attending is away on a trip (window = trip times
                # padded with travel): skip solving, but KEEP the event visible —
                # the calendar must show everything, and a silently vanishing
                # event is impossible to debug. The gray calendar banner is how
                # a mis-timed trip window (e.g. an all-day trip event swallowing
                # the morning bus drop-off) gets noticed and corrected.
                e.trip_suppressed = True
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
    original_trips_to_remove = set()
    for e in all_fetched_events:
        curr = e.start.astimezone()
        end = e.end.astimezone()
        
        # If it's a multi-day background trip, we will slice it into single-day chunks for the UI and solver
        if getattr(e, 'event_type', '') == 'background_trip':
            original_trips_to_remove.add(e.id)
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
                
    for tid in original_trips_to_remove:
        all_events_for_ui.pop(tid, None)

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
            "ai_metadata": combined_ai_metadata,
            # Persisted so /api/overrides/check can explain trip conflicts
            # without re-deriving trip entities outside the refresh
            "trip_metadata": trip_metadata
        })

        if not start_date_str and not end_date_str:
            old_cache = storage.get_cached_schedule() or {}
            storage.set_cached_schedule(data_payload)
            if not draft:
                try:
                    _collect_assignment_changes(old_cache, data_payload, overrides)
                except Exception as notify_err:
                    logger.error(f"Assignment-change collection failed: {notify_err}", exc_info=True)
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
        daily_hash = hash_events(events_to_solve_by_date[date_str])
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

    load_balancing = settings.get("load_balancing_enabled", False)
    load_balancing_metric = settings.get("load_balancing_metric", "occupied_time")
    suggested_routes_enabled = settings.get("suggested_routes_enabled", True)

    base_schedules = {}

    for date_str, daily_fetched in fetched_by_date.items():
        # Check abort at the start of each daily iteration
        check_abort_refresh()

        daily_hash = hash_events(events_to_solve_by_date[date_str])
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

        # ignore_age: only buy pairs we don't have at all. These are free-flow
        # driving durations between fixed addresses, so a cached value never
        # goes out of date; re-fetching stale-but-valid pairs is what burned
        # ~118k Matrix elements in June against a 100k/month allowance.
        maps.prime_matrix_cache(list(daily_locations), ignore_age=True)

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
                daily_events_to_solve, drivers, rules, priority_rules, overrides=overrides, previous_assignments=previous_assignments, driver_events=driver_events_map, passengers=passengers, trip_metadata=trip_metadata, theme=default_theme, load_balancing=load_balancing, load_balancing_metric=load_balancing_metric
            )
            
            unassigned_events = [e for e in daily_events_to_solve if e.id in unassigned]
            assigned_events = [e for e in daily_events_to_solve if e.id in assignments]
            if suggested_routes_enabled:
                ghost_assignments, ghost_drivers = matcher.solve_ghost_routes(unassigned_events, assigned_events, rules, passengers, trip_metadata=trip_metadata)
            else:
                ghost_assignments, ghost_drivers = {}, []
            
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
        daily_hash = hash_events(events_to_solve_by_date[date_str])
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
        

        # NOTE: the daily solver deliberately does NOT persist trip-POI scheduled
        # state. The trip page's CP-SAT scheduler owns the itinerary; the matcher's
        # bounded-errand placement here is used only for the family dashboard's
        # in-memory display, never written back to the trip (writing it back
        # rescheduled the user's itinerary on every refresh).

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
                    a, u, lw = matcher.solve_schedule(d_evs, drvs, rls, prls, overrides=ovr, previous_assignments=prev, driver_events=d_map, passengers=paxs, trip_metadata=meta, theme=t, load_balancing=load_balancing, load_balancing_metric=load_balancing_metric)
                    ue = [e for e in d_evs if e.id in u]
                    ae = [e for e in d_evs if e.id in a]
                    ga, gd = matcher.solve_ghost_routes(ue, ae, rls, paxs, trip_metadata=meta) if suggested_routes_enabled else ({}, [])
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

@app.get("/manifest.json")
def get_manifest():
    # Served from the root, NOT /static: relative URLs in a web app manifest
    # resolve against the manifest's own URL, so at /static/manifest.json the
    # start_url "./app" resolved to /static/app (a 404 on installed PWAs).
    return FileResponse(os.path.join(STATIC_DIR, "manifest.json"), media_type="application/manifest+json")

@app.get("/api/vapid_public_key")
def get_vapid_public_key():
    # Return the URL-safe base64 VAPID public key
    return {"public_key": VAPID_PUBLIC_KEY_STR}

@app.post("/api/push_subscribe")
def push_subscribe(sub: PushSubscription):
    storage.save_push_subscription(sub.driver_id, sub.subscription, member_id=sub.member_id)
    return {"status": "ok"}

@app.get("/api/push_subscriptions/debug")
def debug_push_subscriptions():
    """Who is subscribed on which device — for diagnosing missing pushes."""
    drivers = {d.get('id'): d.get('name') for d in storage.get_all_drivers()}
    out = []
    for s in storage.get_push_subscriptions():
        ep = (s.get('subscription') or {}).get('endpoint') or ''
        host = ep.split('/')[2] if '://' in ep else (ep[:40] or 'unknown')
        out.append({
            "driver_id": s.get('driver_id'),
            "driver_name": drivers.get(s.get('driver_id'), 'unknown'),
            "endpoint_host": host
        })
    return out

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
                                all_cached = False
                                current += timedelta(days=1)
                                continue
                                
                            sched = daily_cache['schedule']
                            for e_id, d_id in sched.get('assignments', {}).items():
                                combined_assignments[e_id] = d_id
                                
                            for e_id in sched.get('unassigned', []):
                                if e_id not in combined_unassigned:
                                    combined_unassigned.append(e_id)
                            
                            for lw in sched.get('lateness_warnings', []):
                                if lw not in combined_lateness_warnings:
                                    combined_lateness_warnings.append(lw)
                            
                            for e_id, d_id in sched.get('ghost_assignments', {}).items():
                                combined_ghost_assignments[e_id] = d_id
                            
                            existing_ghost_ids = {g['id'] for g in combined_ghost_drivers}
                            for g in sched.get('ghost_drivers', []):
                                if g['id'] not in existing_ghost_ids:
                                    combined_ghost_drivers.append(g)
                                    existing_ghost_ids.add(g['id'])
                                    
                            existing_event_ids = {e['id'] if isinstance(e, dict) else getattr(e, 'id', None) for e in combined_events_to_solve}
                            for ev in sched.get('events', []):
                                ev_id = ev['id'] if isinstance(ev, dict) else getattr(ev, 'id', None)
                                if ev_id and ev_id not in existing_event_ids:
                                    combined_events_to_solve.append(ev)
                                    existing_event_ids.add(ev_id)
                            merge_edges(combined_route_edges, sched.get('route_edges', {}))
                            merge_edges(combined_initial_edges, sched.get('initial_edges', {}))
                            merge_edges(combined_final_edges, sched.get('final_edges', {}))
                            
                            for e_id in sched.get('true_unassigned', []):
                                if e_id not in combined_true_unassigned:
                                    combined_true_unassigned.append(e_id)
                                    
                            existing_conflict_strs = {str(c) for c in combined_conflicts}
                            for c in sched.get('conflicts', []):
                                if str(c) not in existing_conflict_strs:
                                    combined_conflicts.append(c)
                                    existing_conflict_strs.add(str(c))
                            
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
                                "unassigned": combined_true_unassigned,
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
                                "diagnostics": global_cache.get("diagnostics", {}),
                                "matched_rules": global_cache.get("matched_rules", {}),
                                "driver_events": global_cache.get("driver_events", {}),
                                "home_location": global_cache.get("home_location", ""),
                                "overridden_events": global_cache.get("overridden_events", []),
                                "passenger_calendar_ids": global_cache.get("passenger_calendar_ids", []),
                                "ai_metadata": global_cache.get("ai_metadata", {}),
                                "drivers": [d.dict() if hasattr(d, 'dict') else d for d in storage.get_all_drivers() if not d.get('is_disabled')],
                                "passengers": storage.get_all_passengers(),
                                "no_location": combined_events_to_solve and [e.get('id') for e in combined_events_to_solve if not e.get('location')] or []
                            }
                            # Hash the combined events list to use as events_hash
                            combined_hash = hash_events(combined_events_to_solve)
                            storage.save_custom_schedule(start_date, end_date, cached, combined_hash)
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

@app.post("/api/admin/backfill_wikidata")
def backfill_wikidata():
    from services import storage, maps
    import urllib.parse
    
    with storage.db_lock:
        trips = storage.trip_metadata_table.all()
        count = 0
        for t in trips:
            updated = False
            
            # Trip Background
            if not t.get('background_url') or 'wikidata_id=' not in t.get('background_url', ''):
                loc = t.get('location', '')
                if loc:
                    res = maps.search_places(loc)
                    if res and res[0].get('wikidata_id'):
                        t['background_url'] = f"api/unsplash/background?query={urllib.parse.quote(loc)}&wikidata_id={res[0]['wikidata_id']}"
                        updated = True

            # POIs
            for poi in t.get('pois', []):
                if not poi.get('wikidata_id'):
                    query = f"{poi.get('name', '')} {poi.get('location', '')}"
                    res = maps.search_places(query)
                    if res:
                        poi['wikidata_id'] = res[0].get('wikidata_id')
                        poi['opening_hours'] = res[0].get('opening_hours')
                        if poi['wikidata_id']:
                            poi['image_url'] = f"api/unsplash/background?query={urllib.parse.quote(poi['name'])}&wikidata_id={poi['wikidata_id']}"
                        updated = True
                        
            # Accommodations
            for acc in t.get('accommodations', []):
                if not acc.get('wikidata_id'):
                    query = f"{acc.get('name', '')} {acc.get('location', '')}"
                    res = maps.search_places(query)
                    if res:
                        acc['wikidata_id'] = res[0].get('wikidata_id')
                        acc['opening_hours'] = res[0].get('opening_hours')
                        updated = True
                        
            if updated:
                storage.trip_metadata_table.update(t, doc_ids=[t.doc_id])
                count += 1
                
    return {"status": "success", "trips_updated": count}

