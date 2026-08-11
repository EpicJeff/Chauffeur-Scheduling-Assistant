import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from fastapi import FastAPI, BackgroundTasks, Response, HTTPException, WebSocket, WebSocketDisconnect, Header, UploadFile, File, Form, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
import asyncio
import time
import uuid as _uuid

LAST_UPDATE_TIME = time.time()
# One id per PROCESS. The stream says hello with it on every (re)connect, so
# a wall panel that sees a different id after a reconnect knows the add-on
# restarted — usually a rebuild — and reloads itself to pick up the new
# frontend instead of running last week's JS until somebody touches it.
BOOT_ID = _uuid.uuid4().hex
# Bumped when panel_* settings change: layout/theme edits made on one device
# must repaint every panel, not just the one holding the settings drawer.
LAST_PROFILE_TIME = 0.0

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

from models.schemas import Driver, Rule, Settings, PriorityRule, ManualOverride, Passenger, Car, FamilyMember, TelemetryEvent, Errand, ErrandRule, StatusTier, StatusProtocol, StatusDay, AssistContact, AssistAssignment, HouseholdTask, ProtectedCommitment
from services import storage, calendar, maps
from services import assist as _assist_svc
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

            # Day-of traffic: the two scheduled buys (a predictive morning
            # pass per leg, a live refine an hour before departure) live in
            # maps.run_day_of_traffic_sweep, driven off the same pending
            # notifications. Self-throttled and hard-marked per stage per
            # day, so this 30s loop can call it blindly.
            try:
                from services import maps as _maps_traffic
                await asyncio.to_thread(_maps_traffic.run_day_of_traffic_sweep, now_ts)
            except Exception as te:
                print(f"Day-of traffic sweep error: {te}")

            for notif in pending_notifications:
                if notif.get("fired"): continue

                notif_id = notif["notif_id"]
                trigger_ts = notif["trigger_timestamp"]
                d_id = notif["driver_id"]

                # Today's traffic moves the fire time UP, never back: the
                # planned trigger came from free-flow minutes, and a push
                # that arrives after the moment it describes is worse than
                # none. Cache read only — the sweep above does the buying.
                eff_ts = trigger_ts
                if notif.get("origin") and notif.get("destination"):
                    try:
                        from services import maps as _maps_traffic
                        eff_ts = min(trigger_ts, _maps_traffic.live_adjusted_trigger(notif))
                    except Exception:
                        eff_ts = trigger_ts

                # Check if it's time to fire (and hasn't expired > 10 mins ago)
                if eff_ts <= now_ts <= trigger_ts + 600:
                    if notif_id not in completed:
                        body = notif["body"]
                        early = int(round((trigger_ts - eff_ts) / 60))
                        if early >= 1:
                            body += f" — traffic is slow, leave {early} min early"
                        send_push(d_id, subs, notif["title"], body, notif_id, notif.get("location"))
                    # Always mark it fired so we don't try again
                    storage.mark_notification_fired(notif_id)
                elif now_ts > trigger_ts + 600:
                    # Expired, mark it fired
                    storage.mark_notification_fired(notif_id)

            # --- Arrival auto-complete: a started leg closes itself when the
            # tracked driver reaches its destination. Cheap when idle (one
            # storage read); the whole point is that stale in_progress flags
            # stop existing at the source instead of lying to every surface
            # that reads them. ---
            try:
                from services import drive_arrival
                for done_leg in drive_arrival.check_arrivals(now_ts):
                    print(f"drive_arrival: auto-completed {done_leg['leg_id']} "
                          f"({done_leg['distance_m']}m from {done_leg['dest']})")
            except Exception as ae:
                print(f"Arrival auto-complete error: {ae}")

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

            # --- Kid evening digest (K1): once per day after kid_digest_time,
            # never inside kid quiet hours. A digest time set inside the quiet
            # window simply never fires (deliberate: a "Tomorrow" digest sent
            # the NEXT morning would preview the wrong day). ---
            try:
                settings = storage.get_settings() or {}
                if settings.get("kid_digest_enabled", True):
                    from services import family_digest
                    now_dt = datetime.now()
                    hh, mm = [int(x) for x in str(settings.get("kid_digest_time", "19:30")).split(":")[:2]]
                    today_str = now_dt.strftime('%Y-%m-%d')
                    if (now_dt.hour, now_dt.minute) >= (hh, mm) \
                            and not family_digest.in_kid_quiet_hours(now_dt, settings) \
                            and storage.get_app_state("kid_digest_last_sent") != today_str:
                        # Marker FIRST (weekly-digest precedent): a half-
                        # failing send must not retry every 30s.
                        storage.set_app_state("kid_digest_last_sent", today_str)
                        _send_kid_digests()
            except Exception as kde:
                print(f"Kid digest error: {kde}")

            # --- School-day-end pickup push (K4c): per child with school
            # hours set, school days only (school_in_session: weekdays, and
            # when configured the school-year bounds + no-school calendar
            # days), once per day, at dismissal. A missed window (>45 min
            # late, e.g. server was down) stays silent — a stale pickup push
            # is worse than none. ---
            try:
                from services import family_digest, school
                now_dt = datetime.now()
                settings = storage.get_settings() or {}
                if school.school_in_session(now_dt.date()) \
                        and not family_digest.in_kid_quiet_hours(now_dt, settings):
                    today_str = now_dt.strftime('%Y-%m-%d')
                    sent = dict(storage.get_app_state("school_end_push_sent") or {})
                    dirty = False
                    for m in storage.get_all_members():
                        if m.get('role') != 'child' or not m.get('school_hours_end'):
                            continue
                        key = f"{m['id']}:{today_str}"
                        if key in sent:
                            continue
                        try:
                            hh, mm = [int(x) for x in str(m['school_hours_end']).split(':')[:2]]
                        except ValueError:
                            continue
                        mins_past = (now_dt.hour * 60 + now_dt.minute) - (hh * 60 + mm)
                        if mins_past < 0:
                            continue
                        sent[key] = time.time()
                        dirty = True
                        if mins_past <= 45:
                            _send_school_end_push(m, now=now_dt)
                    if dirty:
                        cutoff = time.time() - 2 * 86400
                        storage.set_app_state("school_end_push_sent",
                                              {k: v for k, v in sent.items() if v >= cutoff})
            except Exception as se:
                print(f"School-end push error: {se}")

            # --- Daily stats snapshot (late evening, before the day rolls out
            # of the forward-looking schedule cache) ---
            try:
                now_dt = datetime.now()
                today_str = now_dt.strftime('%Y-%m-%d')
                if now_dt.hour >= 21 and storage.get_app_state("daily_stats_last_date") != today_str:
                    from services import family_digest
                    family_digest.record_daily_stats(today_str)
                    storage.set_app_state("daily_stats_last_date", today_str)
            except Exception as se:
                print(f"Daily stats snapshot error: {se}")

            # --- Weekly family digest (Argyle posts to the family channel) ---
            try:
                settings = storage.get_settings() or {}
                if settings.get("weekly_digest_enabled", True):
                    now_dt = datetime.now()
                    hh, mm = [int(x) for x in str(settings.get("weekly_digest_time", "19:00")).split(":")[:2]]
                    today_str = now_dt.strftime('%Y-%m-%d')
                    if now_dt.weekday() == int(settings.get("weekly_digest_day", 6)) \
                            and (now_dt.hour, now_dt.minute) >= (hh, mm) \
                            and storage.get_app_state("weekly_digest_last_sent") != today_str:
                        # Marker set FIRST: a failing post must not retry every
                        # 30s and spam the family channel when it half-works.
                        storage.set_app_state("weekly_digest_last_sent", today_str)
                        from services import family_digest
                        family_digest.post_weekly_digest()
            except Exception as wde:
                print(f"Weekly digest error: {wde}")

            # --- Proactive parent watchers (one consolidated Argyle DM) ---
            try:
                settings = storage.get_settings() or {}
                if settings.get("proactive_watchers_enabled", True):
                    last = float(storage.get_app_state("watchers_last_run") or 0)
                    if time.time() - last >= 1800:
                        # Marker set FIRST — a crashing sweep must not retry
                        # every 30s (same reasoning as the weekly digest).
                        storage.set_app_state("watchers_last_run", time.time())
                        from services import watchers
                        # to_thread: the weekly prep-kit check can sit on a
                        # slow gemma call; never block pending pushes on it.
                        await asyncio.to_thread(watchers.run_watchers)
            except Exception as we:
                print(f"Watcher sweep error: {we}")

            # --- Unanswered requests (load arc A3) ---
            # A request is ALWAYS answered. One that nobody touched expires
            # LOUDLY — to the asker, who otherwise learns nothing, and to
            # whoever owed the answer. An ask that quietly evaporates is the
            # exact failure this object exists to prevent, so this sweep is
            # deliberately NOT quiet-hours gated on its own account: it runs
            # on its own 30-minute cadence and the DM rails carry the timing.
            try:
                last_rq = float(storage.get_app_state("requests_swept") or 0)
                if time.time() - last_rq >= 1800:
                    storage.set_app_state("requests_swept", time.time())
                    from services import requests as _reqsvc
                    await asyncio.to_thread(_reqsvc.sweep)
            except Exception as re_:
                print(f"Request sweep error: {re_}")

            # --- Car readiness sweep (C2, docs/car_telemetry_design.md) ---
            # Charge/fuel-before-drives pushes + away-from-home warnings.
            # Inert when no car has HA fields; quiet-hours gated like the kid
            # pushes; time-gated to 30 min with the marker set FIRST.
            try:
                from services import family_digest
                now_dt = datetime.now()
                if not family_digest.in_kid_quiet_hours(now_dt, storage.get_settings() or {}):
                    last = float(storage.get_app_state("car_readiness_last_run") or 0)
                    if time.time() - last >= 1800:
                        storage.set_app_state("car_readiness_last_run", time.time())
                        from services import cars as cars_svc

                        def _car_push(member, title, body):
                            _notify_member_lanes(member, title, body, '/app')

                        await asyncio.to_thread(cars_svc.run_sweep, _car_push)
            except Exception as ce:
                print(f"Car readiness sweep error: {ce}")

            # --- Prep reminders (M8) ---
            # Soaking beans happens on a different DAY from cooking them, so
            # nothing on tonight's plate can prompt it. Checked every cycle
            # rather than on the 30-min beat: a night-before nudge is only
            # useful in a narrow window, and PREP_GRACE_MINS already stops a
            # stale one going out. Quiet hours are NOT applied — the evening
            # prep time is deliberately late, and a family that set 20:30 has
            # asked to be told at 20:30.
            try:
                from services import meals as _prep_svc

                def _prep_push(member, title, body):
                    # urgent: prep deliberately ignores quiet hours — the
                    # evening prep time is late on purpose, and a family that
                    # set 20:30 has asked to be told at 20:30.
                    _notify_member_lanes(member, title, body, '/shopping', urgent=True)

                fired = await asyncio.to_thread(_prep_svc.run_prep_reminders, _prep_push)
                if fired:
                    print(f"Prep reminders sent: {len(fired)}")
            except Exception as pre:
                print(f"Prep reminder error: {pre}")

            # --- Week meal plan proposal (M6, docs/meal_week_design.md) ---
            # A day or two before the standing grocery run, Argyle brings the
            # span that shop has to cover: "how does this look?" Once per
            # cycle, keyed on the grocery date with the marker set FIRST.
            # Quiet-hours gated — this is a card worth waking up TO, not for.
            try:
                from services import family_digest, meals as _meals_svc
                now_dt = datetime.now()
                if not family_digest.in_kid_quiet_hours(now_dt, storage.get_settings() or {}):
                    last = float(storage.get_app_state("week_plan_last_run") or 0)
                    if time.time() - last >= 1800:
                        storage.set_app_state("week_plan_last_run", time.time())
                        res = await asyncio.to_thread(_meals_svc.propose_week_plan, now_dt)
                        if res.get("status") == "proposed":
                            print(f"Week plan proposed: {res['days']} nights, "
                                  f"{res['dish_count']} dishes")
                        # M7: a list with weight and nowhere to happen.
                        from services import shopping as _shop_svc
                        sres = await asyncio.to_thread(_shop_svc.propose_shopping_errands,
                                                       now_dt)
                        if sres.get("status") == "proposed":
                            print(f"Shopping trip proposed for {len(sres['lists'])} list(s)")
                        # K1: trickle-fill the kiosk board's pictures. A few per
                        # sweep, never on render — the board must not stall
                        # fetching images, and a family with a key configured
                        # should not have to know a button exists.
                        if _meals_svc.unsplash_key():
                            ires = await asyncio.to_thread(_meals_svc.backfill_dish_images, 4)
                            if ires.get("filled"):
                                print(f"Dish pictures: {', '.join(ires['filled'])}")
            except Exception as wpe:
                print(f"Week plan sweep error: {wpe}")

            # --- Status-day calendar sweep (Presence & Status P2) ---
            # Protocol keywords vs the cached schedule window: a matching
            # calendar event auto-sets the status day (adults told with the
            # matched event named; kids only ever hear today/tomorrow, so
            # advance sets carry a built-in review window). Quiet-hours
            # gated like the kid pushes; 30-min cadence, marker set FIRST.
            try:
                from services import family_digest, status_protocols
                now_dt = datetime.now()
                if not family_digest.in_kid_quiet_hours(now_dt, storage.get_settings() or {}):
                    last = float(storage.get_app_state("status_sweep_last_run") or 0)
                    if time.time() - last >= 1800:
                        storage.set_app_state("status_sweep_last_run", time.time())
                        created = await asyncio.to_thread(status_protocols.auto_set_from_calendar)
                        if created:
                            print(f"Status sweep: auto-set {len(created)} day(s) from the calendar")
                        # P3 plan-assist beat: coverage report to the other
                        # adults for upcoming/ongoing cover|help instances
                        # (skips + retries while the re-solve is pending).
                        reported = await asyncio.to_thread(status_protocols.send_coverage_reports)
                        if reported:
                            print(f"Status sweep: sent {len(reported)} coverage report(s)")
                        # Beat timeline: today's adult/affected-audience beats
                        # as one-time DMs (kid beats ride the surfaces).
                        beat_sent = await asyncio.to_thread(status_protocols.send_beat_dms)
                        if beat_sent:
                            print(f"Status sweep: delivered {len(beat_sent)} timeline beat(s)")
            except Exception as spe:
                print(f"Status sweep error: {spe}")

            # --- Presence capture prompt (Presence & Status Slice 4) ---
            # "You're at the game — send the family a moment?" The schedule
            # knows the event is live NOW; the prompt is the feature. 2-min
            # cadence so it lands in the event's opening minutes (per-event
            # marker inside makes re-runs inert); marker set FIRST. Outward
            # prompts go to present ADULTS only (no kid quiet gate needed);
            # the thinking-of-you INVERSION prompts the whole family toward
            # the affected member on cover/help status days and gates kids
            # itself (skip-to-later-sweep, never lost).
            try:
                last = float(storage.get_app_state("presence_prompt_last_run") or 0)
                if time.time() - last >= 120:
                    storage.set_app_state("presence_prompt_last_run", time.time())
                    from services import presence

                    def _presence_push(member, title, body, path):
                        _notify_member_lanes(member, title, body, path)

                    prompted = await asyncio.to_thread(
                        presence.run_capture_prompts, _presence_push)
                    if prompted:
                        print(f"Presence: sent capture prompt(s) for {len(prompted)} event(s)")
                    toy = await asyncio.to_thread(
                        presence.run_thinking_of_you_prompts, _presence_push)
                    if toy:
                        print(f"Presence: sent {len(toy)} thinking-of-you prompt(s)")
            except Exception as ppe:
                print(f"Presence prompt error: {ppe}")

        except Exception as e:
            print(f"Error in push loop: {e}")

        await asyncio.sleep(30)

def _send_tomorrow_digests(subs):
    """One evening digest per driver listing tomorrow's assignments. Content
    comes from family_digest.build_drive_digests (ONE builder, shared with
    the get_drive_digest agent tool); this function only delivers. Drivers
    with nothing tomorrow get nothing. Delivery: posted into the driver's
    Argyle DM (persistent, scrollable; the chat fan-out pushes it too) — the
    raw web-push is only the fallback for drivers with no linked member
    record."""
    from services import storage, family_digest

    digest = family_digest.build_drive_digests()
    weather_line = digest.get("weather")
    tomorrow_iso = digest.get("date")
    label = digest.get("label") or "Tomorrow"

    drivers = dict(digest.get("drivers") or {})
    # Empty-state confirmation: a recently-active driver with nothing tomorrow
    # still gets a "you're free" note, so silence never reads as a broken
    # digest (a bare no-message evening is indistinguishable from a failed
    # send). "Recently active" = drove on any of the last 7 settled days
    # (from the durable daily_stats snapshots — today's isn't taken until
    # 21:00, after this 20:00 send). Non-drivers stay silent.
    recent_days = [(datetime.now().date() - timedelta(days=i)).isoformat()
                   for i in range(1, 8)]
    active = {a_id for row in storage.get_daily_stats(recent_days)
              for a_id, s in (row.get("drivers") or {}).items()
              if (s.get("drives") or 0) > 0}
    for a_id in active:
        if a_id not in drivers:
            drivers[a_id] = {"title": f"{label}: no drives",
                             "lines": ["🎉 You're free — nothing on the schedule."],
                             "count": 0}

    # The household briefing (load arc A6): every parent/adult gets tomorrow
    # for the WHOLE family — openings first, handled underneath — instead of
    # the per-driver silo, because the parent who isn't driving otherwise
    # learns the day changed by happening to look at a screen. Helpers and
    # unlinked drivers keep the per-driver digest: another family's nanny has
    # no business receiving this household's whole picture.
    briefed_member_ids = set()
    try:
        briefing = family_digest.build_household_briefing()
        if briefing.get('lines'):
            b_lines = ([weather_line] if weather_line else []) + briefing['lines']
            opens = briefing.get('open_count') or 0
            b_title = (f"🏠 {briefing['label']}: {opens} thing"
                       f"{'s' if opens != 1 else ''} still open"
                       if opens else f"🏠 {briefing['label']}, all handled")
            from services.agent_tools_v2 import _post_chat_message
            argyle = storage.ensure_argyle_member()
            for m in storage.get_all_members():
                if m.get('role') not in ('parent', 'adult') or m.get('system'):
                    continue
                try:
                    dm = storage.get_or_create_dm(argyle['id'], m['id'])
                    _post_chat_message(dm, argyle, b_title + "\n" + "\n".join(b_lines))
                    briefed_member_ids.add(m['id'])
                except Exception as be:
                    print(f"Briefing DM failed for {m.get('name')}: {be}")
    except Exception as bfe:
        print(f"Household briefing failed (falling back to per-driver): {bfe}")

    subscribed = {s.get("driver_id") for s in subs}
    for d_id, d in drivers.items():
        lines = list(d["lines"])
        if weather_line:
            lines.insert(0, weather_line)
        title = d["title"]
        member = storage.get_member_by_driver_id(d_id)
        if member and member['id'] in briefed_member_ids:
            continue        # the briefing already covers their tomorrow
        if member:
            try:
                from services.agent_tools_v2 import _post_chat_message
                argyle = storage.ensure_argyle_member()
                dm = storage.get_or_create_dm(argyle['id'], member['id'])
                _post_chat_message(dm, argyle, title + "\n" + "\n".join(lines))
                continue
            except Exception as dme:
                print(f"Tomorrow digest DM failed for {member.get('name')}: {dme}")
        if d_id in subscribed:
            send_push(d_id, subs, title, "\n".join(lines),
                      f"digest_{tomorrow_iso}", actions=[])

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

    # K2: kid-worded pushes for near-term driver changes ride the same
    # netted buffer (churn within a run already collapsed to nothing).
    try:
        _notify_kids_driver_changes(buffered)
    except Exception as ke:
        print(f"Kid driver-change push failed: {ke}")

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


def _shelf_order(request: Request) -> list:
    """Which buttons the panel shelf shows, in order, resolved SERVER-SIDE.

    The shelf used to be rendered in the template's own declaration order and
    then reordered by JavaScript once the panel profile arrived — so the family
    watched the buttons shuffle on every page load. The server already knows
    the answer (it is the same `resolve_tabs` the profile endpoint returns), so
    it can simply render them in the right order and there is nothing to
    correct afterwards.

    Falls back to every destination if anything here fails: a shelf is how you
    get around a wall panel, and no shelf is worse than a mis-ordered one.
    """
    try:
        from services import home_board as _hb
        return _hb.resolve_tabs(request.query_params.get('tabs'),
                                storage.get_settings() or {})
    except Exception as e:
        print(f"shelf order resolve failed: {e}")
        try:
            from services import home_board as _hb
            return list(_hb.DEFAULT_TABS)
        except Exception:
            return []


templates.env.globals['shelf_order'] = _shelf_order

# --- UI Routes ---
@app.get("/")
def root_redirect(request: Request):
    """The board, not the solver's output. Landing on the driver schedule made
    sense when that was the whole app; the home board is now the thing that
    answers "what is going on" without being asked, which is what an address
    with nothing after it is asking for. Query params are carried across so a
    panel pointed at the bare host still arrives in panel mode."""
    q = request.url.query
    return RedirectResponse(url="home" + (f"?{q}" if q else ""))

@app.get("/dashboard")
def dashboard_legacy():
    return RedirectResponse(url="dashboard_v2")

@app.get("/dashboard_v2")
def dashboard(request: Request):
    response = templates.TemplateResponse(request=request, name="dashboard.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/home")
def home_board_page(request: Request):
    """The wall-panel home screen: what is happening now, then a grid of
    glances. Opened with ?panel=true it is the panel's resting state; opened
    in an ordinary browser it is also where the panel gets configured (the
    tiles are picked while you look at them)."""
    response = templates.TemplateResponse(request=request, name="home.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/api/home_board")
def home_board_api(widgets: Optional[str] = None):
    """The whole board in ONE payload. Six tiles fetching themselves would be
    six requests per tick on a display that runs sixteen hours a day; this is
    one, cached briefly so a second panel costs nothing."""
    from services import home_board
    return home_board.build(
        requested=widgets,
        kid_digest_fn=lambda: _build_kid_digests(_kid_digest_default_date()))

@app.get("/api/home_board/catalog")
def home_board_catalog():
    """The pickable tiles, for the panel setup UI."""
    from services import home_board
    return home_board.catalog()

@app.get("/api/panel/profile")
def panel_profile(tabs: Optional[str] = None, widgets: Optional[str] = None):
    """What this panel shows, resolved: URL params, then the stored profile,
    then the defaults. The shelf calls this so a display pointed at a bare
    /home?panel=true still comes up configured."""
    from services import home_board
    return home_board.profile(tabs=tabs, widgets=widgets)

@app.get("/api/panel/screensaver")
def panel_screensaver_playlist():
    """Fresh picture URLs for one screensaver activation — called when the
    idle timer fires, not at page load, so a panel that has been up for weeks
    still shows this week's photos."""
    from services import home_board
    return home_board.screensaver_playlist()

@app.get("/api/panel/media-image/{rel_path:path}")
def panel_media_image(rel_path: str):
    """Serve one image from the HA media share for the screensaver. The
    playlist only ever emits paths _media_share_images produced, but this is
    a URL anyone can type, so containment is re-checked here from scratch."""
    from services import home_board
    root = os.path.realpath(home_board.MEDIA_SHARE_ROOT)
    full = os.path.realpath(os.path.join(root, rel_path))
    if not (full == root or full.startswith(root + os.sep)):
        raise HTTPException(status_code=404, detail="Not found")
    if not (os.path.isfile(full) and full.lower().endswith(home_board._IMAGE_EXTS)):
        raise HTTPException(status_code=404, detail="Not found")
    import mimetypes
    mime = mimetypes.guess_type(full)[0] or 'image/jpeg'
    # Immutable-ish: the screensaver re-lists the folder every activation, so
    # a day of browser caching costs nothing and spares the share re-reads.
    return FileResponse(full, media_type=mime,
                        headers={'Cache-Control': 'public, max-age=86400'})

@app.get("/app")
def driver_app(request: Request):
    # no-store like the dashboard: iOS caches installed-PWA start pages hard,
    # leaving phones on stale HTML for days after a release.
    response = templates.TemplateResponse(request=request, name="app.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/config")
def config(request: Request):
    # Mapbox context for the gas-station picker map (same quota gate the trip
    # map uses — the map only instantiates when the user opens the picker).
    import datetime as _dt
    current_month = _dt.datetime.now().strftime("%Y-%m")
    allow_map_loads = maps.get_map_option('enable_mapbox_map_loads', True) \
        and storage.get_mapbox_usage(current_month, 'map_loads') \
        < maps.get_map_option('mapbox_map_loads_limit', 45000)
    return templates.TemplateResponse(request=request, name="config.html", context={
        "mapbox_key": maps.get_mapbox_api_key() or "",
        "allow_map_loads": allow_map_loads,
    })

@app.get("/calendar", response_class=HTMLResponse)
def calendar_view(request: Request):
    return templates.TemplateResponse(request=request, name="calendar.html")

@app.get("/moments", response_class=HTMLResponse)
def moments_gallery(request: Request):
    """The Moments gallery — the wall-panel surface for looking BACK at
    moments (the hearth overlay/rail only ever shows the newest)."""
    return templates.TemplateResponse(request=request, name="moments.html")

@app.get("/moment", response_class=HTMLResponse)
def moment_popup(request: Request):
    """Standalone one-moment page in the hearth style — built to be iframed
    by an HA browser_mod popup on the `chauffeur_moment` event (it renders
    the newest moment; ?message_id= pins a specific one)."""
    response = templates.TemplateResponse(request=request, name="moment.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/errands")
def errands(request: Request):
    return templates.TemplateResponse(request=request, name="errands.html")

@app.get("/occasions")
def occasions_page(request: Request):
    return templates.TemplateResponse(request=request, name="occasions.html")

@app.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html")

@app.get("/chores")
def chores_page(request: Request):
    response = templates.TemplateResponse(request=request, name="chores.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/shopping")
def shopping_page(request: Request):
    response = templates.TemplateResponse(request=request, name="shopping.html")
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
    # Write it down. A trip's real dates live on its Google event, and this is
    # the only place they are ever assembled — so the home board, which cannot
    # call Google on a 60-second timer, reads the snapshot this leaves behind.
    try:
        storage.set_cached_trips(trips_list)
    except Exception as e:
        print(f"trips snapshot failed: {e}")
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

    # Kiosk displays get a read-only compact view: no editing surfaces, but
    # the same map (quota-gated like the full page — kiosks reload often, so
    # the monthly map-load limit is the safety valve).
    name = "trip_kiosk.html" if request.query_params.get("kiosk") == "true" else "trip.html"
    response = templates.TemplateResponse(request=request, name=name, context={
        "event_id": event_id,
        "mapbox_key": mapbox_key,
        "allow_map_loads": allow_map_loads
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.get("/api/weather/daily")
def weather_daily(days: int = 7, start: str = None):
    """Per-day forecast chips for the calendar Agenda view. Weather is
    garnish: any HA/entity problem returns [] and the UI omits the chips."""
    import datetime
    from services import ha_api, family_digest
    try:
        start_date = datetime.date.fromisoformat(start) if start else datetime.date.today()
    except (ValueError, TypeError):
        start_date = datetime.date.today()
    days = max(1, min(days, 14))
    try:
        settings = storage.get_settings() or {}
        forecast = ha_api.get_weather_forecast(settings.get('weather_entity') or None)
        by_date = {}
        for f in forecast:
            d = str(f.get('datetime') or '')[:10]
            if d and d not in by_date:
                by_date[d] = f
        out = []
        for i in range(days):
            d = (start_date + datetime.timedelta(days=i)).isoformat()
            f = by_date.get(d)
            if not f:
                continue
            cond = str(f.get('condition') or '')
            out.append({
                "date": d,
                "emoji": family_digest._WEATHER_EMOJI.get(cond, '🌤️'),
                "condition": cond,
                "high": f.get('temperature'),
                "low": f.get('templow'),
                "precip": f.get('precipitation_probability'),
            })
        return out
    except Exception as e:
        print(f"weather_daily failed: {e}")
        return []


@app.get("/api/school/status")
def school_status():
    """What the school-day system currently believes (Config diagnostics):
    in-session today, detected school years, cached closure count."""
    from services import school
    return school.status()


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
    data = driver.model_dump() if hasattr(driver, 'model_dump') else driver.dict()
    # Stage gate (load arc A4): a driver named for a child member is that
    # child learning to drive, and driving arrives with Copilot. A name that
    # matches nobody (a grandparent, a helper) is none of this gate's
    # business — same name-match storage uses to link driver to member.
    from services import stages
    name = (data.get('name') or '').strip().lower()
    member = next((m for m in storage.get_all_members()
                   if (m.get('name') or '').strip().lower() == name), None)
    if member and not member.get('driver_id'):
        # First-time setup only: the config edit flow is DELETE-then-POST with
        # the same driver id, and a member already behind the wheel must keep
        # their profile editable even if their stage was later pinned down.
        block = stages.refuse_driver_setup(member)
        if block:
            raise HTTPException(status_code=400, detail=block)
    doc_id = storage.add_driver(data)
    if member and member.get('role') == 'child' \
            and member.get('assist_tier') != 'assist':
        # The teen and the wheel (household_load_design.md): a Copilot who
        # drives COVERS work without CARRYING the household's share — the
        # assist tier keeps their drives out of the adults' ledger while the
        # role keeps their kid lens intact.
        storage.update_member(member['id'], {'assist_tier': 'assist'})
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
        last_profile_seen = LAST_PROFILE_TIME
        last_ping = time.time()
        try:
            # Hello first: the boot id lets a panel notice a server restart on
            # reconnect and reload itself. Existing consumers match the exact
            # string "update" and ignore everything else, so this is additive.
            yield f"data: hello:{BOOT_ID}\n\n"
            while True:
                await asyncio.sleep(1)
                now = time.time()
                if LAST_PROFILE_TIME > last_profile_seen:
                    last_profile_seen = LAST_PROFILE_TIME
                    yield "data: profile\n\n"
                    last_ping = now
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

# --- Cars API ---
@app.get("/api/cars")
def get_cars():
    return storage.get_all_cars()

@app.post("/api/cars")
def create_car(car: Car, background_tasks: BackgroundTasks):
    doc_id = storage.add_car(car.model_dump() if hasattr(car, 'model_dump') else car.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/cars/{doc_id}")
def update_car(doc_id: int, car: Car, background_tasks: BackgroundTasks):
    storage.update_car(doc_id, car.model_dump() if hasattr(car, 'model_dump') else car.dict())
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "updated"}

@app.delete("/api/cars/{doc_id}")
def delete_car(doc_id: int, background_tasks: BackgroundTasks):
    storage.delete_car(doc_id)
    background_tasks.add_task(refresh_schedule_logic)
    return {"status": "deleted"}

@app.get("/api/cars/stations/nearby")
def nearby_gas_stations(limit: int = 6):
    """Closest gas stations to the family's home location — feeds the Config
    'home gas station' picker so the setting is a choice, not a typing test.
    One Mapbox category search (same 'category' cap C3 meters); geocode of
    home is cached. Distance is haversine from home, display only."""
    from services import maps
    from services.cars import _haversine_m
    settings = storage.get_settings() or {}
    home = (settings.get('home_location') or '').strip()
    if not home:
        return {"stations": [], "error": "Set your Home Location (General tab) first."}
    try:
        o = maps.geocode_address(home)
    except Exception:
        o = None
    if not o:
        return {"stations": [], "error": "Couldn't locate your home address."}
    try:
        results = maps.search_category('gas_station', o[0], o[1],
                                       limit=max(1, min(int(limit), 10)))
    except Exception as e:
        print(f"Nearby station search failed: {e}")
        results = []
    if not results:
        return {"stations": [], "error": "No stations found (Mapbox may be disabled)."}
    stations = []
    for r in results:
        entry = {"name": r.get("name"), "address": r.get("address"),
                 "lat": r.get("lat"), "lon": r.get("lon")}
        try:
            entry["distance_km"] = round(
                _haversine_m(o[0], o[1], float(r["lat"]), float(r["lon"])) / 1000, 1)
        except (KeyError, TypeError, ValueError):
            entry["distance_km"] = None
        stations.append(entry)
    stations.sort(key=lambda s: s["distance_km"] if s["distance_km"] is not None else 999)
    # What the home pin actually resolved to — surfaced in the UI so a
    # city-center geocode is VISIBLE instead of silently wrong.
    home_row = storage.get_cached_geocode(maps.extract_street_address(home)) \
        or storage.get_cached_geocode(home) or {}
    return {"stations": stations, "home": {"lat": o[0], "lon": o[1]},
            "home_label": home_row.get('display_name') or home,
            "home_precision": home_row.get('precision') or 'exact'}

# --- ICS Feed Subscriptions API (intake arc phase 1) ---

class IcsFeedCreate(BaseModel):
    url: str
    calendar_id: str = ""            # required for calendar mode
    name: Optional[str] = None
    # K4b task mode: 'tasks' + member_id lands assignments on the kid's
    # school list instead of a calendar (never solver load).
    target_kind: str = "calendar"    # calendar | tasks
    member_id: Optional[str] = None

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

    target_kind = req.target_kind if req.target_kind in ('calendar', 'tasks') else 'calendar'
    if target_kind == 'tasks':
        member = storage.get_member(req.member_id or '')
        if not member or member.get('role') != 'child':
            raise HTTPException(status_code=400,
                                detail="Task feeds need a child member to own the list")
    elif not req.calendar_id:
        raise HTTPException(status_code=400, detail="Calendar feeds need a target calendar")

    name = (req.name or '').strip() or parsed.get('name')
    if not name:
        name = url.split('/')[2] if '://' in url else url
    feed_id = storage.add_ics_feed({
        'url': url,
        'name': name,
        'calendar_id': req.calendar_id,
        'target_kind': target_kind,
        'member_id': req.member_id,
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
    # Edit-before-approve: any field the parent touched on the card overrides
    # the extracted value; omitted fields keep the proposal's own.
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    all_day: Optional[bool] = None
    # 'errand' target extras — an errand needs what a proposal doesn't have.
    # `location` doubles as the event target's location edit.
    location: Optional[str] = None
    duration_mins: Optional[int] = None
    # Approve-as-configure (event target): the card is the WHOLE editor, so
    # approving is the last touch — no follow-up trip to Google Calendar for
    # location/recurrence, no second stop at the schedule inbox for who rides.
    description: Optional[str] = None
    recurrence: Optional[str] = None          # daily|weekly|biweekly|monthly
    recurrence_until: Optional[str] = None    # YYYY-MM-DD, inclusive
    passenger_ids: Optional[List[str]] = None
    driver_ids: Optional[List[str]] = None

# The four cadences a family actually types; the weekday/monthday ride on
# DTSTART, so the rules stay minimal and Google fills in the rest.
_INTAKE_RRULES = {'daily': 'FREQ=DAILY', 'weekly': 'FREQ=WEEKLY',
                  'biweekly': 'FREQ=WEEKLY;INTERVAL=2', 'monthly': 'FREQ=MONTHLY'}

@app.get("/api/ingest/config")
def get_ingest_config():
    s = storage.get_settings() or {}
    return {
        'ingest_email_enabled': bool(s.get('ingest_email_enabled')),
        'ingest_email_host': s.get('ingest_email_host') or 'imap.gmail.com',
        'ingest_email_user': s.get('ingest_email_user') or '',
        'has_password': bool(s.get('ingest_email_password')),
        'ingest_sender_defaults': s.get('ingest_sender_defaults') or [],
        'ingest_sender_blocklist': s.get('ingest_sender_blocklist') or [],
    }


@app.get("/api/ingest/ignored-senders")
def ignored_senders(min_ignored: int = 2):
    """Senders the family has repeatedly ignored, read from the PROPOSAL
    LEDGER rather than the live queue.

    The block offer used to hang off a pending proposal card — which is the
    transient thing. Ignore every proposal from a sender and the cards leave
    the queue, so the offer disappeared at exactly the moment the family had
    most thoroughly demonstrated they wanted it. Proposals are never pruned,
    so the history is complete however long ago the ignoring happened.

    `approved` rides along because a sender you sometimes act on is not a
    sender to block, and a count of ignores alone would hide that.
    """
    from services import email_ingest
    blocklist = (storage.get_settings() or {}).get('ingest_sender_blocklist') or []
    streaks = storage.get_app_state('intake_ignore_streaks') or {}
    by_sender = {}
    for p in storage.get_proposals():
        sender = (p.get('source_from') or '').strip().lower()
        if not sender:
            continue                       # photo capture has no sender
        row = by_sender.setdefault(sender, {
            'sender': sender, 'ignored': 0, 'approved': 0, 'other': 0,
            'last_subject': '', 'last_ts': 0,
        })
        status = p.get('status')
        if status == 'ignored':
            row['ignored'] += 1
        elif status == 'approved':
            row['approved'] += 1
        else:
            row['other'] += 1
        ts = p.get('created_at') or 0
        if ts >= row['last_ts']:
            row['last_ts'] = ts
            row['last_subject'] = p.get('source_subject') or ''
    out = []
    for row in by_sender.values():
        if row['ignored'] < max(1, int(min_ignored or 2)):
            continue
        if email_ingest.sender_blocked(row['sender'], blocklist):
            continue                       # already handled, nothing to offer
        at = row['sender'].rfind('@')
        row['domain'] = row['sender'][at:] if at > -1 else ''
        row['streak'] = int(streaks.get(row['sender']) or 0)
        out.append(row)
    # Most ignored first, and never-approved ahead of sometimes-useful.
    out.sort(key=lambda r: (r['approved'] > 0, -r['ignored']))
    return out


class IngestBlockRequest(BaseModel):
    pattern: str                      # an address or a bare domain fragment
    label: Optional[str] = ""         # what the family will recognise it as


@app.post("/api/ingest/block-sender")
def block_ingest_sender(req: IngestBlockRequest):
    """Stop reading mail from an address or a whole domain.

    This exists because the app used to notice a sender the family kept
    ignoring and then send them to Gmail to build a filter — advice, not an
    action, for a problem the app could see and fix in one click. Matching is
    substring, so '@teamsnap.com' blocks every address that platform sends
    from."""
    pattern = (req.pattern or '').strip().lower()
    if not pattern:
        raise HTTPException(status_code=400, detail="A pattern is required")
    s = storage.get_settings() or {}
    current = [e for e in (s.get('ingest_sender_blocklist') or [])
               if isinstance(e, dict) and (e.get('pattern') or '').strip().lower() != pattern]
    current.append({'pattern': pattern, 'label': (req.label or '').strip(),
                    'added_at': time.time()})
    storage.patch_settings({'ingest_sender_blocklist': current})
    # The streak was the reason the offer appeared; it has been answered.
    streaks = storage.get_app_state('intake_ignore_streaks') or {}
    if streaks:
        storage.set_app_state('intake_ignore_streaks',
                              {k: v for k, v in streaks.items() if pattern not in (k or '')})
    storage.add_ingest_log({'from': pattern, 'subject': '(blocklist)',
                            'outcome': f'blocked — mail matching {pattern} will be skipped'})
    return {"status": "blocked", "pattern": pattern,
            "ingest_sender_blocklist": current}


@app.post("/api/ingest/unblock-sender")
def unblock_ingest_sender(req: IngestBlockRequest):
    pattern = (req.pattern or '').strip().lower()
    s = storage.get_settings() or {}
    current = [e for e in (s.get('ingest_sender_blocklist') or [])
               if isinstance(e, dict) and (e.get('pattern') or '').strip().lower() != pattern]
    storage.patch_settings({'ingest_sender_blocklist': current})
    storage.add_ingest_log({'from': pattern, 'subject': '(blocklist)',
                            'outcome': f'unblocked — mail matching {pattern} will be read again'})
    return {"status": "unblocked", "ingest_sender_blocklist": current}

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

_PHOTO_MAX_BYTES = 8 * 1024 * 1024

@app.post("/api/ingest/photo")
async def ingest_photo(photo: UploadFile = File(...), caption: str = Form('')):
    """Intake phase 3 (vision capture): snap the backpack flyer / screenshot
    the group text → the same proposal queue as email ingest."""
    import base64
    data = await photo.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (8MB max)")
    mime = (photo.content_type or '').lower()
    if not mime.startswith('image/'):
        raise HTTPException(status_code=400, detail="Only images are supported")
    from services import email_ingest
    summary = email_ingest.run_photo_ingest(
        base64.b64encode(data).decode('ascii'), mime, (caption or '').strip())
    summary['pending'] = len(storage.get_proposals('proposed'))
    return summary

@app.post("/share")
async def pwa_share_target(photos: list[UploadFile] = File(default=[]),
                           title: str = Form(''), text: str = Form('')):
    """Android PWA share-target (manifest.json share_target → this route,
    which is why the manifest is served from the origin root): sharing an
    image to the installed app drops it into the intake pipeline, then
    bounces into the PWA. iOS has never supported PWA share targets — the
    in-app 📸 buttons are the capture path there."""
    import base64
    caption = ' '.join(x for x in [(title or '').strip(), (text or '').strip()] if x)[:200]
    for up in photos[:1]:  # v1: first image only
        data = await up.read()
        mime = (up.content_type or '').lower()
        if data and len(data) <= _PHOTO_MAX_BYTES and mime.startswith('image/'):
            from services import email_ingest
            email_ingest.run_photo_ingest(base64.b64encode(data).decode('ascii'), mime, caption)
    return RedirectResponse(url='app?view=family', status_code=303)

@app.get("/api/proposals")
def list_proposals(status: str = 'proposed'):
    props = storage.get_proposals(status if status != 'all' else None)
    # 3+ consecutive ignores from a sender → the approval surfaces show a hint.
    streaks = storage.get_app_state('intake_ignore_streaks') or {}
    for p in props:
        n = streaks.get((p.get('source_from') or '').strip().lower())
        if n and int(n) >= 3:
            p['sender_ignores'] = int(n)
    return sorted(props, key=lambda p: p.get('start') or '')


def _record_intake_feedback(prop: dict, approved_target: str = None):
    """Intake phase-2 (a): deterministic learned priors, no LLM. An approval
    remembers sender → target (prefills the next proposal from that sender,
    behind explicit sender defaults) and resets the sender's ignore streak;
    an ignore increments the streak (the UI hints at 3+). Last approval wins."""
    sender = (prop.get('source_from') or '').strip().lower()
    if not sender:
        return
    try:
        if approved_target:
            routes = storage.get_app_state('intake_learned_routes') or {}
            prev = routes.get(sender) or {}
            routes[sender] = {'target': approved_target,
                              'count': int(prev.get('count') or 0) + 1,
                              'ts': time.time()}
            storage.set_app_state('intake_learned_routes', routes)
            streaks = storage.get_app_state('intake_ignore_streaks') or {}
            if streaks.get(sender):
                streaks[sender] = 0
                storage.set_app_state('intake_ignore_streaks', streaks)
        else:
            streaks = storage.get_app_state('intake_ignore_streaks') or {}
            streaks[sender] = int(streaks.get(sender) or 0) + 1
            storage.set_app_state('intake_ignore_streaks', streaks)
    except Exception as e:
        print(f"Intake feedback recording failed: {e}")

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
    all_day = req.all_day if req.all_day is not None else bool(prop.get('all_day'))

    # Intake phase-2 (c): the 'errand' target turns a proposal into a DRIVE
    # ERRAND the solver schedules ("buy poster board by Thursday") instead of
    # a calendar event. The parent supplies the two things a proposal lacks —
    # location and duration — and the due date becomes the scheduling window.
    if req.calendar_id == 'errand':
        location = (req.location or '').strip() or (prop.get('location') or '').strip()
        if not location:
            raise HTTPException(status_code=400, detail="An errand needs a location")
        due = (start or '')[:10]
        try:
            due_date = datetime.strptime(due, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Proposal has no usable date")
        from services import maps
        errand = Errand(
            title=title.lstrip('📌').strip() or title,
            duration_mins=max(5, int(req.duration_mins or 30)),
            location=maps.resolve_routable_location(location),
            window_days=max(1, (due_date - datetime.now().date()).days + 1),
            tags=['intake'],
        )
        create_errand(errand, background_tasks)  # applies ErrandRules + refresh
        storage.update_proposal(proposal_id, {
            'status': 'approved', 'calendar_id': 'errand',
            'created_errand_id': errand.id, 'title': title, 'start': start, 'end': end,
        })
        _record_intake_feedback(prop, 'errand')
        return {"status": "approved", "errand_id": errand.id,
                "message": f'Added "{errand.title}" as a drive errand 🚗'}

    # Load arc A2: 'household_task' is the FOURTH intake target, and the one
    # the capture layer had been missing. The extraction prompt already names
    # "permission slip due, payment due, picture day" as things to find — and
    # until now they fit nowhere: not a calendar event, not an errand (which
    # demands a location because an errand IS a drive), not a kid task (that
    # is a child's own school list). They became a fake all-day event or
    # nothing at all.
    if (req.calendar_id or '') == 'household_task':
        from models.schemas import HouseholdTask
        due = (start or '')[:10]
        try:
            datetime.strptime(due, '%Y-%m-%d')
        except (ValueError, TypeError):
            due = None                 # a task may legitimately have no deadline
        task = HouseholdTask(title=title, due_date=due, source='intake',
                             source_ref=proposal_id,
                             notes=(req.description or '').strip()
                                   or prop.get('notes') or '').model_dump()
        storage.add_household_task(task)
        storage.update_proposal(proposal_id, {
            'status': 'approved', 'calendar_id': req.calendar_id,
            'created_task_id': task['id'], 'title': title, 'start': start, 'end': end,
        })
        _record_intake_feedback(prop, req.calendar_id)
        # Deliberately unassigned: "the household owes this" is a real state,
        # and picking an owner here would just move the deciding back onto
        # whoever happened to tap Approve.
        return {"status": "approved", "task_id": task['id'],
                "message": f'Added "{title}" to the household list 📋'}

    # K4b: a 'tasks:{member_id}' target lands the item on that kid's school
    # list instead of any calendar — never solver load, never an all-day 📌.
    if (req.calendar_id or '').startswith('tasks:'):
        member_id = req.calendar_id.split(':', 1)[1]
        member = storage.get_member(member_id)
        if not member or member.get('role') != 'child':
            raise HTTPException(status_code=400, detail="Task target must be a child member")
        due = (start or '')[:10]
        try:
            datetime.strptime(due, '%Y-%m-%d')
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Proposal has no usable due date")
        from models.schemas import KidTask
        from services.ics_sync import _task_kind_for
        task = KidTask(member_id=member_id, title=title, due_date=due,
                       kind=_task_kind_for(title), source='intake',
                       source_ref=proposal_id,
                       notes=(req.description or '').strip()
                             or prop.get('notes') or '').model_dump()
        storage.add_kid_task(task)
        storage.update_proposal(proposal_id, {
            'status': 'approved', 'calendar_id': req.calendar_id,
            'created_task_id': task['id'], 'title': title, 'start': start, 'end': end,
        })
        _record_intake_feedback(prop, req.calendar_id)
        return {"status": "approved", "task_id": task['id'],
                "message": f"Added to {member.get('name')}'s school list 📚"}

    # Approve-as-configure: an edited description replaces the extracted
    # notes; the source attribution line survives either way, because "where
    # did this event come from" is the question a parent asks in October.
    description_parts = []
    notes = (req.description or '').strip() or (prop.get('notes') or '')
    if notes:
        description_parts.append(notes)
    description_parts.append(f"From family email: {prop.get('source_from', '')} — {prop.get('source_subject', '')}")

    if all_day:
        body_start, body_end = {'date': start[:10]}, {'date': end[:10]}
    else:
        body_start, body_end = {'dateTime': start}, {'dateTime': end}
        # Name the calendar's real zone — an offset-only dateTime pins the
        # event to a fixed GMT offset in the Calendar edit UI.
        tz = gcal.get_calendar_timezone(req.calendar_id)
        if tz:
            body_start['timeZone'] = body_end['timeZone'] = tz
    body = {
        'summary': title,
        'start': body_start,
        'end': body_end,
        'description': '\n'.join(description_parts),
        'extendedProperties': {'private': {'intake_proposal_id': proposal_id}},
    }
    location = (req.location or '').strip() or (prop.get('location') or '').strip()
    if location:
        # Email-extracted locations are usually bare venue names; resolve to
        # a routable address so the solver can route to the event.
        from services import maps
        body['location'] = maps.resolve_routable_location(location)

    rec = (req.recurrence or '').strip().lower()
    if rec:
        rule = _INTAKE_RRULES.get(rec)
        if not rule:
            raise HTTPException(status_code=400,
                                detail=f"Unknown recurrence '{rec}'")
        until = (req.recurrence_until or '').strip()
        if until:
            try:
                datetime.strptime(until, '%Y-%m-%d')
            except (ValueError, TypeError):
                raise HTTPException(status_code=400,
                                    detail="Recurrence end must be YYYY-MM-DD")
            # RFC5545: UNTIL's type must match DTSTART's — a DATE for all-day
            # events, UTC date-time for timed ones.
            compact = until.replace('-', '')
            rule += f";UNTIL={compact}" if all_day else f";UNTIL={compact}T235959Z"
        body['recurrence'] = [f"RRULE:{rule}"]

    gid = gcal.insert_event(req.calendar_id, body)
    if not gid:
        raise HTTPException(status_code=502, detail="Google Calendar rejected the event")

    # The Chauffeur half of approval: attendees picked on the card become the
    # event config, keyed by the new google id — a recurring series' instances
    # find it through their recurring_event_id fallback. This is what used to
    # need a second stop at the schedule inbox; with a config in place the
    # event never lands there. No attendees picked -> no config, and the inbox
    # stays the honest state for a ride nobody has claimed.
    conf = {}
    if req.passenger_ids:
        conf['passenger_ids'] = [str(x) for x in req.passenger_ids if str(x).strip()]
    if req.driver_ids:
        conf['driver_ids'] = [str(x) for x in req.driver_ids if str(x).strip()]
    conf = {k: v for k, v in conf.items() if v}
    if conf:
        storage.set_event_config(gid, conf)

    storage.update_proposal(proposal_id, {
        'status': 'approved', 'calendar_id': req.calendar_id,
        'created_event_id': gid, 'title': title, 'start': start, 'end': end,
    })
    _record_intake_feedback(prop, req.calendar_id)
    background_tasks.add_task(trigger_background_refresh)
    bits = [f'Added "{title}" 📅']
    if rec:
        bits.append('repeating 🔁')
    if conf:
        bits.append('set up for the schedule 🚗')
    return {"status": "approved", "event_id": gid,
            "message": ' — '.join(bits) if len(bits) > 1 else bits[0]}

@app.get("/api/proposals/misfiled")
def list_misfiled_proposals():
    """To-dos that were approved onto a CALENDAR and became all-day 📌 events.

    Until v2.170.0 the `household_task` branch of the approve endpoint existed
    and no dropdown offered it, so a household to-do's only plausible target
    was somebody's calendar. Those items then landed in the one place nothing
    in Chauffeur could see.

    Identified from the PROPOSAL LEDGER, not by scanning calendars for the 📌
    the extractor prepends: the other three approval branches write
    `created_task_id`/`created_errand_id`, so a task-kind proposal carrying
    `created_event_id` means exactly "a to-do that became a calendar event".
    Emoji-matching a calendar would guess back something we already knew, and
    would collect every legitimate all-day event as a false positive.
    """
    out = []
    for p in storage.get_proposals('approved'):
        if p.get('kind') != 'task' or not p.get('created_event_id'):
            continue
        out.append({
            'id': p.get('id'),
            'title': (p.get('title') or '').lstrip('📌').strip() or p.get('title'),
            'start': p.get('start'), 'notes': p.get('notes') or '',
            'calendar_id': p.get('calendar_id'),
            'source_subject': p.get('source_subject') or '',
        })
    return sorted(out, key=lambda r: r.get('start') or '')

@app.post("/api/proposals/{proposal_id}/refile")
def refile_proposal(proposal_id: str, background_tasks: BackgroundTasks):
    """Move one mis-filed to-do onto the household list and take the stray
    calendar event back off. Both halves, because leaving the event behind
    would put one obligation in two places with no rule for which one you
    complete."""
    from services import calendar as gcal
    from models.schemas import HouseholdTask
    prop = storage.get_proposal(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if prop.get('kind') != 'task' or not prop.get('created_event_id'):
        raise HTTPException(status_code=400,
                            detail="That proposal isn't a to-do sitting on a calendar.")
    due = (prop.get('start') or '')[:10]
    try:
        datetime.strptime(due, '%Y-%m-%d')
    except (ValueError, TypeError):
        due = None            # a task may legitimately have no deadline
    # The 📌 is a proposal-display convention; the household list has its own.
    title = (prop.get('title') or '').lstrip('📌').strip() or prop.get('title')
    task = HouseholdTask(title=title, due_date=due, source='intake',
                         source_ref=proposal_id,
                         notes=prop.get('notes') or '').model_dump()
    storage.add_household_task(task)
    removed = gcal.remove_event(prop.get('calendar_id'), prop['created_event_id'])
    storage.update_proposal(proposal_id, {
        'calendar_id': 'household_task', 'created_task_id': task['id'],
        'created_event_id': None,
    })
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "refiled", "task_id": task['id'],
            "removed_event": bool(removed),
            "message": f'Moved "{title}" to the household list 📋'
                       + ('' if removed else ' — the calendar event needs deleting by hand.')}

@app.post("/api/proposals/{proposal_id}/ignore")
def ignore_proposal(proposal_id: str):
    prop = storage.get_proposal(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
    storage.update_proposal(proposal_id, {'status': 'ignored'})
    _record_intake_feedback(prop)
    return {"status": "ignored"}


class ActionProposalAct(BaseModel):
    act: str            # 'approve' | 'dismiss'
    member_id: str      # the family member tapping the button


@app.get("/api/action-proposals")
def list_action_proposals(status: str = "proposed"):
    """Pending (or filtered) agent action proposals — the dashboard's
    approvals banner polls this (C3, docs/car_errand_proposals_design.md)."""
    return storage.get_action_proposals(status=status or None)


@app.post("/api/action-proposals/{proposal_id}/act")
def act_on_action_proposal(proposal_id: str, req: ActionProposalAct, background_tasks: BackgroundTasks):
    """Approve or dismiss an agent action proposal from a chat card. Approval
    executes the typed action (parent-scoped) and Argyle posts the outcome —
    with the updated card — back into the proposal's origin channel."""
    from services import chat_actions
    from services.agent_tools_v2 import _post_chat_message
    approver = storage.get_member(req.member_id)
    res = chat_actions.act_on_proposal(proposal_id, (req.act or '').strip().lower(), approver)

    prop = storage.get_action_proposal(proposal_id)
    channel = storage.get_channel(prop.get('channel_id')) if prop and prop.get('channel_id') else None
    if channel and res.get('message'):
        try:
            _post_chat_message(channel, storage.ensure_argyle_member(), res['message'], card=res.get('card'))
        except Exception as e:
            logger.error(f"Action-proposal follow-up post failed: {e}")
    if res.get('schedule_dirty'):
        background_tasks.add_task(trigger_background_refresh)
    return res

# --- Family Members API (overlay over drivers/passengers) ---

def _public_member(m: dict) -> dict:
    """Strip PIN secrets; expose has_pin instead."""
    out = {k: v for k, v in m.items() if k not in ('pin_hash', 'pin_salt', 'pin')}
    out['has_pin'] = bool(m.get('pin_hash'))
    return out

# --- Protected commitments (load arc A6) ---
# The one place an adult's time is FOR something rather than an obstacle.

@app.get("/api/commitments")
def list_commitments(member_id: Optional[str] = None):
    rows = storage.get_protected_commitments(member_id=member_id,
                                             include_inactive=True)
    names = {m['id']: m.get('name') for m in storage.get_all_members()}
    for r in rows:
        r['member_name'] = names.get(r.get('member_id'))
    return rows

@app.post("/api/commitments")
def create_commitment(pc: ProtectedCommitment, background_tasks: BackgroundTasks):
    data = pc.model_dump()
    if not (data.get('title') or '').strip():
        raise HTTPException(status_code=400, detail="It needs a name")
    if not storage.get_member(data.get('member_id') or ''):
        raise HTTPException(status_code=404, detail="Member not found")
    storage.add_protected_commitment(data)
    # The solver has to learn the ban now, not at the next routine refresh —
    # protecting an evening that stays scheduled is not protecting it.
    background_tasks.add_task(trigger_background_refresh, None, None, True)
    return {"status": "success", "id": data['id']}

@app.patch("/api/commitments/{commitment_id}")
def patch_commitment(commitment_id: str, updates: dict = Body(...),
                     background_tasks: BackgroundTasks = None):
    clean = {k: v for k, v in (updates or {}).items()
             if k in ProtectedCommitment.model_fields and k not in ('id', 'created_at')}
    if not storage.update_protected_commitment(commitment_id, clean):
        raise HTTPException(status_code=404, detail="Commitment not found")
    if background_tasks:
        background_tasks.add_task(trigger_background_refresh, None, None, True)
    return {"status": "success"}

@app.delete("/api/commitments/{commitment_id}")
def remove_commitment(commitment_id: str, background_tasks: BackgroundTasks):
    storage.delete_protected_commitment(commitment_id)
    background_tasks.add_task(trigger_background_refresh, None, None, True)
    return {"status": "success"}

# --- Stages: the child that grows (load arc A4) ---

@app.get("/api/stages")
def get_stages():
    """The bands, and where every child currently sits."""
    from services import stages
    kids = []
    for m in storage.get_all_members():
        if m.get('role') != 'child':
            continue
        kids.append({
            'member_id': m['id'], 'name': m.get('name'),
            'birthdate': m.get('birthdate'), 'age': stages.age_of(m),
            'stage': stages.stage_of(m),
            'suggested': stages.suggested_stage(m),
            'pinned': m.get('stage_override'),
            'acknowledged': m.get('stage_acknowledged'),
            'capabilities': stages.capabilities(m),
        })
    return {'stages': stages.STAGES, 'cutoffs': stages.cutoffs(),
            'kids': kids, 'pending': stages.pending_promotions()}

@app.post("/api/stages/{member_id}/acknowledge")
def acknowledge_stage(member_id: str, body: dict = Body(default={})):
    """A parent confirms a child has moved up. Growing up is GRANTED, never
    silently switched — and nothing is deleted in the process."""
    from services import stages
    res = stages.acknowledge(member_id, body.get('stage'))
    if res.get('status') != 'success':
        raise HTTPException(status_code=400, detail=res.get('message'))
    return res

# --- Requests: the ask as a first-class object (load arc A3) ---
# A kid could report but not ASK; an adult could only TAKE a drive from their
# partner. One object for both, always answered.

class RequestCreate(BaseModel):
    from_member: str
    body: str
    kind: str = 'other'
    to_member: Optional[str] = None
    subject_ref: Optional[str] = None
    subject_label: Optional[str] = ""

class RequestDecide(BaseModel):
    accept: bool
    member_id: str
    reason: Optional[str] = ""

@app.get("/api/requests")
def list_requests(member_id: str):
    from services import requests as _req
    if not storage.get_member(member_id):
        raise HTTPException(status_code=404, detail="Member not found")
    return _req.summary_for(member_id)

@app.post("/api/requests")
def create_request(req: RequestCreate, background_tasks: BackgroundTasks):
    from services import requests as _req
    if not storage.get_member(req.from_member):
        raise HTTPException(status_code=404, detail="Member not found")
    if not (req.body or '').strip():
        raise HTTPException(status_code=400, detail="An ask needs words")
    # Off-request: the fan-out touches push endpoints and HA.
    row = _req.create(req.from_member, req.body, kind=req.kind,
                      to_member_id=req.to_member, subject_ref=req.subject_ref,
                      subject_label=req.subject_label or "")
    if row.get('status') == 'error':      # stage-gated (load arc A4)
        raise HTTPException(status_code=403, detail=row.get('message'))
    return {"status": "success", "id": row['id']}

@app.post("/api/requests/{request_id}/decide")
def decide_request(request_id: str, req: RequestDecide, background_tasks: BackgroundTasks):
    from services import requests as _req
    res = _req.decide(request_id, bool(req.accept), req.member_id, req.reason or "")
    if res.get('status') != 'success':
        raise HTTPException(status_code=400, detail=res.get('message'))
    if res.get('schedule_dirty'):
        background_tasks.add_task(trigger_background_refresh, None, None, True)
    return res

@app.post("/api/requests/{request_id}/cancel")
def cancel_request(request_id: str, body: dict = Body(...)):
    from services import requests as _req
    res = _req.cancel(request_id, body.get('member_id'))
    if res.get('status') != 'success':
        raise HTTPException(status_code=400, detail=res.get('message'))
    return res

# --- Household tasks (load arc A2 — the keystone) ---
# Work with a deadline and no destination. Task = do something, errand = go
# somewhere. `assigned_to` optional, and UNASSIGNED IS A REAL STATE meaning
# the household owes it — that is where delegation lives.

@app.get("/api/household-tasks")
def list_household_tasks(assigned_to: Optional[str] = None,
                         include_done: bool = False,
                         unassigned_only: bool = False):
    import datetime as _dt
    tasks = storage.get_household_tasks(assigned_to=assigned_to,
                                        include_done=include_done,
                                        unassigned_only=unassigned_only)
    today = _dt.date.today().isoformat()
    members = {m['id']: m for m in storage.get_all_members(include_system=True)}
    # Outside hands hold tasks too (load arc A1 slice 2). Resolving the name
    # here is what stops an `assist:` holder rendering as "nobody yet", which
    # is the failure mode of a second id space nobody told the reader about.
    contacts = {c['id']: c for c in storage.get_assist_contacts(include_inactive=True)}
    for t in tasks:
        due = t.get('due_date')
        t['past_due'] = bool(due and due < today and t.get('status') != 'done')
        t['due_today'] = bool(due and due == today)
        holder = t.get('assigned_to') or ''
        if _assist_svc.is_assist_id(holder):
            c = contacts.get(_assist_svc.contact_id(holder))
            t['assigned_to_name'] = c.get('name') if c else None
            t['assigned_to_assist'] = True
        else:
            owner = members.get(holder)
            t['assigned_to_name'] = owner.get('name') if owner else None
            t['assigned_to_assist'] = False
    return tasks

def _refuse_kid_task_assignment(member_id):
    """Stage gate (load arc A4): real household jobs arrive with Navigator.
    Server-side like the Sprout request gate — not merely hidden in the UI."""
    if not member_id:
        return
    from services import stages
    block = stages.refuse_task_assignment(storage.get_member(member_id))
    if block:
        raise HTTPException(status_code=400, detail=block)

@app.post("/api/household-tasks")
def create_household_task(task: HouseholdTask):
    data = task.model_dump()
    if not (data.get('title') or '').strip():
        raise HTTPException(status_code=400, detail="A task needs a title")
    _refuse_kid_task_assignment(data.get('assigned_to'))
    storage.add_household_task(data)
    return {"status": "success", "id": data['id']}

@app.patch("/api/household-tasks/{task_id}")
def patch_household_task(task_id: str, updates: dict = Body(...)):
    if not storage.get_household_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    clean = {k: v for k, v in (updates or {}).items()
             if k in HouseholdTask.model_fields and k not in ('id', 'created_at')}
    if 'assigned_to' in clean:
        _refuse_kid_task_assignment(clean.get('assigned_to'))
    storage.update_household_task(task_id, clean)
    return {"status": "success"}

@app.post("/api/household-tasks/{task_id}/complete")
def complete_household_task_endpoint(task_id: str, body: dict = Body(default={})):
    row = storage.complete_household_task(task_id, done=bool(body.get('done', True)),
                                          member_id=body.get('member_id'))
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    out = {"status": "success"}
    if row.get('next_due_date'):
        out['message'] = f"Done — the next one is due {row['next_due_date']}."
        out['next_due_date'] = row['next_due_date']
    return out

@app.delete("/api/household-tasks/{task_id}")
def remove_household_task(task_id: str):
    if not storage.get_household_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    storage.delete_household_task(task_id)
    return {"status": "success"}

@app.get("/api/household-load")
def household_load(days: int = 30):
    """Who is carrying what. **States, never scores** — no percentages, no
    leaderboard, no chart. Adults need division of labour, not gamification,
    and a fairness chart between two spouses is a fight generator.

    Assist-tier members are counted SEPARATELY, never folded into the
    household's split: a teenager who drives six times and cooks twice must
    not make the parents look even (load arc, "covering is not carrying").
    """
    import datetime as _dt
    from services import family_digest
    cutoff = (_dt.date.today() - _dt.timedelta(days=max(1, min(days, 180)))).isoformat()
    members = [m for m in storage.get_all_members() if not m.get('system')]
    by_id = {m['id']: m for m in members}

    rows = {}
    for m in members:
        if m.get('role') in ('parent', 'adult') or m.get('assist_tier') == 'assist':
            rows[m['id']] = {'member_id': m['id'], 'name': m.get('name'),
                             'assist': m.get('assist_tier') == 'assist'
                                       or m.get('role') == 'helper',
                             'tasks': 0, 'drives': 0}

    # Outside hands appear on the assisting side the moment they finish
    # something — covering is not carrying, so their work is visible and is
    # never folded into the household's split. The row is created lazily
    # because a contact who has done nothing this window is not a gap.
    contacts_by_id = {c['id']: c for c in storage.get_assist_contacts(include_inactive=True)}
    for t in storage.get_household_tasks(include_done=True):
        if t.get('status') != 'done' or not t.get('assigned_to'):
            continue
        done_day = _dt.datetime.fromtimestamp(t.get('completed_at') or 0).date().isoformat()
        if done_day < cutoff:
            continue
        holder = t['assigned_to']
        if _assist_svc.is_assist_id(holder) and holder not in rows:
            c = contacts_by_id.get(_assist_svc.contact_id(holder))
            if not c:
                continue                      # deleted contact: not somebody's load
            rows[holder] = {'member_id': holder, 'name': c.get('name'),
                            'assist': True, 'tasks': 0, 'drives': 0}
        r = rows.get(holder)
        if r:
            r['tasks'] += 1

    # Drives come from the existing daily snapshots, which already exclude
    # ghost drivers (services/family_digest.record_daily_stats).
    span = [(_dt.date.today() - _dt.timedelta(days=i)).isoformat()
            for i in range(max(1, min(days, 180)))]
    try:
        stats = storage.get_daily_stats(span) or []
    except Exception:
        stats = []
    drv_to_member = {m.get('driver_id'): m['id'] for m in members if m.get('driver_id')}
    for day in stats:
        for drv_id, d in (day.get('drivers') or {}).items():
            mid = drv_to_member.get(drv_id)
            if mid and mid in rows:
                rows[mid]['drives'] += int(d.get('drives') or 0)

    household = [r for r in rows.values() if not r['assist']]
    assisting = [r for r in rows.values() if r['assist']]
    for r in household + assisting:
        r['total'] = r['tasks'] + r['drives']
    household.sort(key=lambda r: -r['total'])
    assisting.sort(key=lambda r: -r['total'])

    # The sentence, in the occasions `_load_balance` voice: it counts and
    # names and deliberately never ranks or scores.
    line = None
    carried = [r for r in household if r['total']]
    if len(carried) >= 2 and sum(r['total'] for r in carried) >= 6:
        top, total = carried[0], sum(r['total'] for r in carried)
        line = (f"{top['total']} of the {total} things done in the last "
                f"{days} days were {top['name']}'s.")
    elif len(carried) == 1 and carried[0]['total'] >= 4:
        line = f"Everything logged in the last {days} days was {carried[0]['name']}'s."
    return {"days": days, "household": household, "assisting": assisting,
            "line": line}

# --- Outside hands: assist contacts and the work they cover (load arc A1) ---
# A contact is somebody outside this household who does work for it — a carpool
# parent, the neighbour who does the dishes. They have no account, which is the
# line against the `helper` ROLE (an external person who does hold the app).
# Coverage is the third assignment state: a covered event leaves the solver.

@app.get("/api/assist-contacts")
def list_assist_contacts(include_inactive: bool = False):
    from services import assist as assist_svc
    contacts = storage.get_assist_contacts(include_inactive=include_inactive)
    counts, series_counts = {}, {}
    for a in storage.get_assist_assignments():
        cid = a.get('contact_id')
        if not cid:
            continue
        counts[cid] = counts.get(cid, 0) + 1
        if (a.get('scope') or 'instance') == 'series':
            series_counts[cid] = series_counts.get(cid, 0) + 1
    for c in contacts:
        c['covering_count'] = counts.get(c['id'], 0)
        # Counted apart so the delete warning can't say "1 drive comes back"
        # about a standing every-Tuesday arrangement.
        c['covering_series'] = series_counts.get(c['id'], 0)
    # `helps_with` is the normalised work-surface list every picker filters on,
    # computed in one place so the synonym table never gets a second copy.
    return assist_svc.decorate(contacts)

@app.post("/api/assist-contacts")
def create_assist_contact(contact: AssistContact):
    data = contact.model_dump()
    if not (data.get('name') or '').strip():
        raise HTTPException(status_code=400, detail="A contact needs a name")
    storage.add_assist_contact(data)
    return {"status": "success", "id": data['id']}

@app.patch("/api/assist-contacts/{contact_id}")
def patch_assist_contact(contact_id: str, updates: dict = Body(...)):
    if not storage.get_assist_contact(contact_id):
        raise HTTPException(status_code=404, detail="Contact not found")
    # id and created_at are the row's identity, never client-settable.
    clean = {k: v for k, v in (updates or {}).items()
             if k in AssistContact.model_fields and k not in ('id', 'created_at')}
    storage.update_assist_contact(contact_id, clean)
    return {"status": "success"}

@app.delete("/api/assist-contacts/{contact_id}")
def remove_assist_contact(contact_id: str, background_tasks: BackgroundTasks):
    if not storage.get_assist_contact(contact_id):
        raise HTTPException(status_code=404, detail="Contact not found")
    # Deleting drops their coverage too (storage enforces it), which hands
    # those events back to the solver — so the schedule has to be rebuilt or
    # the day would keep showing them as covered by somebody who is gone.
    storage.delete_assist_contact(contact_id)
    background_tasks.add_task(trigger_background_refresh, None, None, True)
    return {"status": "success"}

class AssistCoverageRequest(BaseModel):
    event_id: str
    contact_id: Optional[str] = None   # None/empty clears the coverage
    note: Optional[str] = ""
    # 'instance' (this occurrence) | 'series' (every occurrence). Same choice
    # the event modal already offers for configs and overrides.
    scope: Optional[str] = 'instance'
    actor: Optional[str] = None


def _assist_event_context(event_id: str):
    """The cached-schedule event behind an id, plus its split-leg parent. The
    server resolves the series key and the date itself rather than trusting a
    client to compute them — otherwise the dashboard, the phone and the agent
    each get their own chance to key coverage differently."""
    base = str(event_id or '')
    for suffix in ('_dropoff', '_pickup'):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    sched = storage.get_cached_schedule() or {}
    for ev in sched.get('events', []):
        if ev.get('id') == base:
            return base, ev
    return base, None


@app.post("/api/assist-coverage")
def set_assist_coverage(req: AssistCoverageRequest, background_tasks: BackgroundTasks):
    """Hand an event to somebody outside the house, or take it back.

    Either way the schedule must be re-solved: handing it over frees a
    household driver for the rest of the day, and taking it back puts the
    event in front of the solver again. force_refresh, because the events
    themselves did not change — only who is covering them.

    Scope mirrors event configs and overrides: 'series' writes against the bare
    `recurring_event_id` so future occurrences — including ones not yet fetched
    into the sync window — are covered by the same row, and an instance row
    still wins over it.
    """
    if not req.event_id:
        raise HTTPException(status_code=400, detail="event_id is required")
    base_id, ev = _assist_event_context(req.event_id)
    rec = (ev or {}).get('recurring_event_id')
    scope = 'series' if (req.scope == 'series' and rec) else 'instance'
    key = str(rec) if scope == 'series' else base_id
    span = 'every time it comes round' if scope == 'series' else 'this one'

    if req.contact_id:
        contact = storage.get_assist_contact(req.contact_id)
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        storage.set_assist_assignment(
            key, req.contact_id, req.note or "", scope=scope,
            # A series row has no single date and must never archive on one.
            event_date=('' if scope == 'series' else str((ev or {}).get('start') or '')[:10]),
            event_title=(ev or {}).get('title') or '', actor=req.actor)
        msg = f"{contact.get('relation_label') or contact.get('name')} is covering {span}."
    else:
        # Clearing takes BOTH keys: the family means "we're driving it", and
        # leaving the series row behind would silently re-cover the occurrence
        # on the next solve.
        storage.clear_assist_assignment(base_id, actor=req.actor)
        if rec:
            storage.clear_assist_assignment(str(rec), actor=req.actor)
        msg = "Back on the family's plate."
    background_tasks.add_task(trigger_background_refresh, None, None, True)
    return {"status": "success", "message": msg, "scope": scope}


@app.get("/api/assist-history")
def list_assist_history(contact_id: str = None, limit: int = 200):
    """The permanent record: every hand-over, take-back and archived ride.
    Nothing in the solve path reads this — it exists to be looked at."""
    rows = storage.get_assist_history(contact_id=contact_id, limit=limit)
    names = {c['id']: (c.get('relation_label') or c.get('name'))
             for c in storage.get_assist_contacts(include_inactive=True)}
    for r in rows:
        r['contact_name'] = names.get(r.get('contact_id')) or '(removed)'
    return rows

@app.get("/api/members")
def get_members():
    members = storage.get_all_members()
    drivers = {d.get('id'): d for d in storage.get_all_drivers()}
    passengers = {p.get('id'): p for p in storage.get_all_passengers()}
    from services import stages
    out = []
    for m in members:
        pub = _public_member(m)
        pub['driver'] = drivers.get(m.get('driver_id'))
        pub['passenger'] = passengers.get(m.get('passenger_id'))
        # Stages (load arc A4): the PWA shell asks for a capability BY NAME
        # rather than working one out from an age, so no surface downstream
        # ever has to know a birthday.
        if m.get('role') == 'child':
            pub['stage'] = stages.stage_of(m)
            pub['capabilities'] = stages.capabilities(m)
        out.append(pub)
    return out

@app.post("/api/members")
def create_member(member: FamilyMember):
    data = member.model_dump()
    cal_ids = data.pop('calendar_ids', None)
    storage.add_member(data)
    if cal_ids:
        storage.set_member_calendars(data['id'], cal_ids)
    return {"id": data['id'], "status": "created"}

@app.put("/api/members/{member_id}")
def update_member_endpoint(member_id: str, updates: dict):
    # Partial update; id/links are managed via merge/split, PINs via the pin
    # endpoints — never via blind PUT.
    for field in ('id', 'doc_id', 'driver', 'passenger', 'pin_hash', 'pin_salt', 'has_pin', 'pin'):
        updates.pop(field, None)
    # Calendars go through set_member_calendars, never a blind write: it also
    # rewrites the driver/passenger mirrors and drops the schedule caches.
    cal_ids = updates.pop('calendar_ids', None)
    if 'role' in updates:
        if updates['role'] not in ('parent', 'adult', 'child', 'helper'):
            raise HTTPException(status_code=400, detail="Invalid role")
        updates['is_child'] = updates['role'] == 'child'
    if updates:
        if not storage.update_member(member_id, updates):
            raise HTTPException(status_code=404, detail="Member not found")
    elif not storage.get_member(member_id):
        raise HTTPException(status_code=404, detail="Member not found")
    if cal_ids is not None:
        storage.set_member_calendars(member_id, cal_ids)
    if 'color_code' in updates:
        # Identity color is the single source of truth — keep the legacy
        # driver record in step so anything still reading it agrees.
        m = storage.get_member(member_id)
        if m and m.get('driver_id'):
            storage.update_driver_fields(m['driver_id'], {'color_code': updates['color_code']})
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

def _push_message_event(channel_id, recipients, meta=None):
    """meta (optional) rides the SSE payload — e.g. {'moment': {...}} so an
    open app can pop a new moment instead of just bumping a badge."""
    global _MESSAGE_SEQ
    _MESSAGE_SEQ += 1
    entry = {'seq': _MESSAGE_SEQ, 'channel_id': channel_id,
             'recipients': recipients}
    if meta:
        entry.update(meta)
    MESSAGE_EVENTS.append(entry)
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
    if channel.get('kind') in ('dm', 'group'):
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
        elif kind == 'group':
            title = f"{sender_name} · {channel.get('title') or 'Group'}"
        elif kind == 'event':
            title = f"{sender_name} · {channel.get('title') or 'Event chat'}"
        else:
            title = f"{sender_name} · Family"
        body = (message.get('body') or '')[:180]
        base = (storage.get_settings().get('public_base_url') or '').rstrip('/')
        # Relative for web push (sw navigates on the PWA's own origin —
        # immune to public_base_url mismatch), absolute for HA companion.
        path = f"/app?open_channel={channel['id']}"
        recipients = _channel_recipient_members(channel)
        if kind == 'event' and message.get('attachment'):
            # Presence moment: access stays family-wide (the thread), but the
            # PUSH routes only to the kept-away adults — never to whoever the
            # schedule places AT the event (don't ping the parent standing
            # next to the sender), never to kids (moments ride their existing
            # surfaces, no new pings).
            try:
                from services import presence
                recipients = presence.moment_push_audience(channel)
                title = f"📸 {channel.get('title') or 'A family moment'}"
                caption = (message.get('body') or '').strip()
                body = (f"{sender_name} shared a moment"
                        + (f": {caption[:140]}" if caption else " — you couldn't be there 💙"))
            except Exception as pe:
                print(f"Moment audience resolution failed (falling back): {pe}")
            # HA event bus: a bare "a moment just happened" ping so the
            # family's automations can react — e.g. browser_mod popping an
            # iframe of /moment (which always renders the newest moment) on
            # the wall panel. Deliberately payload-free: the popup page
            # fetches the moment itself, so nothing sensitive rides the bus.
            # EVENT channels only — a private thinking-of-you DM must never
            # pop on a shared panel.
            try:
                ha_api.fire_event('chauffeur_moment', {})
            except Exception as fe:
                print(f"Moment HA event failed: {fe}")
        for m in recipients:
            if m['id'] == message['sender_member_id']:
                continue
            # Quiet hours on the identity (load arc A6): the message still
            # lands in the thread — only the PING is skipped. Skip, never
            # defer: a chat push at 8am about a 10pm message is noise.
            from services import family_digest as _fd
            if _fd.in_member_quiet_hours(m):
                continue
            lanes = m.get('notify_lanes') or 'all'
            if lanes in ('all', 'push'):
                send_push_to_member(m['id'], title, body, path)
            svc = m.get('notify_service') if lanes in ('all', 'ha') else None
            if svc:
                svc_name = svc.split('.', 1)[1] if '.' in svc else svc
                payload = {"title": title, "message": body}
                if base:
                    payload["data"] = {"url": f"{base}{path}"}
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

# --- Room announcements (services/announce.py): speak INTO a room over HA.
# The hand path for the announce_to_room agent tool — the map page's announce
# bar posts here. Results come back in the agent-tool shape (status + spoken
# message) rather than HTTP errors, because "I don't know that room, rooms I
# know: …" is the useful thing to show whichever surface asked.

class AnnounceRequest(BaseModel):
    room: str
    message: str
    recipient_member_id: Optional[str] = None

@app.get("/api/announce/rooms")
def announce_rooms():
    """Rooms that can be announced into: HA areas holding a satellite or media
    player (or carrying a pin), each with its resolved target and the full
    candidate list so a parent can pin a specific speaker."""
    from services import announce as announce_svc, ha_api
    pins = storage.get_settings().get('announce_targets') or {}
    names = {s.get('entity_id'): (s.get('attributes') or {}).get('friendly_name') or s.get('entity_id')
             for s in ha_api.get_states(ttl=10)}
    out = []
    for area in ha_api.get_area_map():
        candidates = [e for e in (area.get('entities') or [])
                      if e.startswith(('assist_satellite.', 'media_player.'))]
        if not candidates and area.get('id') not in pins:
            continue
        target = announce_svc.pick_target(area)
        out.append({'id': area.get('id'), 'name': area.get('name'),
                    'candidates': [{'entity_id': e, 'name': names.get(e, e)} for e in candidates],
                    'pinned': pins.get(area.get('id')),
                    'target': target[1] if target else None,
                    'kind': target[0] if target else None})
    return out

class VoiceRequest(BaseModel):
    voice: str

@app.get("/api/announce/voices")
def announce_voices():
    """Argyle's possible voices: the pipeline's TTS engine asked for its own
    voice list, plus which one is current. Empty voices means the picker has
    nothing to offer (legacy engine name, or HA unreachable) and the UI hides
    itself rather than showing an empty dropdown."""
    from services import ha_api
    pipe = ha_api.get_pipeline_tts() or {}
    engine = pipe.get('engine') or ''
    if not engine.startswith('tts.'):
        return {'engine': engine or None, 'current': pipe.get('voice'), 'voices': []}
    return {'engine': engine, 'language': pipe.get('language'),
            'current': pipe.get('voice'),
            'voices': ha_api.list_tts_voices(engine, pipe.get('language'))}

@app.post("/api/announce/voice")
def set_announce_voice(req: VoiceRequest):
    """One dropdown, every mouth: writes the voice onto the Argyle pipeline
    itself (HA stays the single source of truth), so satellite replies,
    announcements and the tts.speak fallback all change together."""
    from services import ha_api
    if ha_api.set_pipeline_voice(req.voice):
        return {'status': 'success', 'message': "Argyle's voice is changed everywhere."}
    return {'status': 'error',
            'message': "Home Assistant wouldn't take the voice change — is the pipeline reachable?"}

@app.post("/api/announce")
def post_announce(req: AnnounceRequest):
    from services import announce as announce_svc
    recipient = storage.get_member(req.recipient_member_id) if req.recipient_member_id else None
    # Sender stays Argyle: the map page lives on shared screens, and a shared
    # screen doesn't know whose finger tapped it.
    return announce_svc.announce_and_echo(req.room, req.message, recipient=recipient)

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

def _notify_member_lanes(member, title, body, path='/app', urgent=False):
    """One member, all lanes: web push + HA companion notify.

    Web push deep links are RELATIVE: the service worker navigates within
    whatever origin the PWA is actually installed on (LAN, ingress, tunnel),
    so a mismatched/stale public_base_url can never 404 the tap — the bug
    that sent intake-proposal taps to a dead absolute URL. Only the HA
    companion lane, which has no origin context, gets the absolute link.

    Quiet hours on the identity (load arc A6): a non-urgent send inside the
    member's window SKIPS — never defers — matching the kid rule ("a stale
    on-the-way push is worse than none"). `urgent=True` escapes: a 5:30am
    departure has to fire at 5:10 inside a window that runs to eight, or the
    first night-shift parent misses a drive. Children keep the kid-quiet
    machinery; this window is the adult's own. `notify_lanes` (all|push|ha)
    settles the double-delivery a member with both lanes always had."""
    try:
        from services import family_digest as _fd
        if not urgent and _fd.in_member_quiet_hours(member):
            return
        lanes = member.get('notify_lanes') or 'all'
        base = (storage.get_settings().get('public_base_url') or '').rstrip('/')
        if lanes in ('all', 'push'):
            send_push_to_member(member['id'], title, body, path)
        svc = member.get('notify_service') if lanes in ('all', 'ha') else None
        if svc:
            from services import ha_api
            svc_name = svc.split('.', 1)[1] if '.' in svc else svc
            payload = {"title": title, "message": body}
            if base:
                payload["data"] = {"url": f"{base}{path}"}
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
    emoji: Optional[str] = None
    description: Optional[str] = ""
    points: int = 10
    recurrence: str = 'once'
    eligible_member_ids: list = []
    # A permanent arrangement — this chore is theirs, every time it recurs.
    # A member id, or 'assist:<id>'. Per-instance assignment is /assign.
    owner: Optional[str] = None

def _clean_emoji(v):
    # A glyph, not a caption: cap at 8 chars (covers ZWJ sequences), blank -> None
    # so render paths fall back to the kid_glyphs keyword guess.
    v = (v or '').strip()
    return v[:8] or None

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
    # Outside hands claim chores too — the same shape as an adult claiming one,
    # earning nothing. Resolving the name here is what stops a chore Maddie did
    # rendering with a blank claimant.
    contacts = {c['id']: c for c in storage.get_assist_contacts(include_inactive=True)}
    for c in chores:
        holder = c.get('claimed_by') or ''
        if _assist_svc.is_assist_id(holder):
            hand = contacts.get(_assist_svc.contact_id(holder))
            c['claimed_by_name'] = hand.get('name') if hand else None
            c['claimed_by_color'] = '#64748b'
            c['claimed_by_assist'] = True
        else:
            claimant = members.get(holder)
            c['claimed_by_name'] = claimant.get('name') if claimant else None
            c['claimed_by_color'] = claimant.get('color_code') if claimant else None
            c['claimed_by_assist'] = False
        owner = c.get('owner') or ''
        if owner:
            o = (contacts.get(_assist_svc.contact_id(owner))
                 if _assist_svc.is_assist_id(owner) else members.get(owner))
            c['owner_name'] = (o or {}).get('name')
        else:
            c['owner_name'] = None
        # "Mom gave you this" and "you took this" are different facts about
        # the day, so the card can tell them apart.
        c['assigned_by_name'] = (members.get(c.get('assigned_by')) or {}).get('name')
    order = {'done': 0, 'open': 1, 'claimed': 2, 'verified': 3}
    chores.sort(key=lambda c: (order.get(c.get('state'), 9), -(c.get('points') or 0)))
    return chores

def _owned_chore_fields(owner):
    """Owning IS holding it. A chore that is somebody's job never sits in the
    pot waiting to be picked up — that is the difference between 'anyone can
    take this' and 'this is yours'. Clearing the owner puts it back up for
    grabs."""
    if not owner:
        return {'owner': None, 'state': 'open', 'claimed_by': None,
                'claimed_at': None, 'assigned_by': None}
    name, _is_assist = _chore_claimant(owner)
    if not name:
        raise HTTPException(status_code=404, detail="Nobody by that id to own it")
    return {'owner': owner, 'state': 'claimed', 'claimed_by': owner,
            'claimed_at': time.time(), 'assigned_by': None,
            'rejected_reason': None}

@app.post("/api/chores")
def create_chore(req: ChoreCreateRequest, background_tasks: BackgroundTasks):
    from models.schemas import Chore
    _validate_chore_fields(req)
    chore = Chore(title=req.title.strip(), emoji=_clean_emoji(req.emoji),
                  description=req.description or '',
                  points=int(req.points), recurrence=req.recurrence,
                  eligible_member_ids=req.eligible_member_ids or []).model_dump()
    chore.update(_owned_chore_fields(req.owner))
    storage.add_chore(chore)
    # An owned chore is nobody's to pick up, so the "new chore posted" blast to
    # the eligible kids would be an invitation to something already taken.
    if not req.owner:
        background_tasks.add_task(_notify_chore_event, 'posted', chore)
    return chore

@app.put("/api/chores/{chore_id}")
def edit_chore(chore_id: str, req: ChoreCreateRequest):
    _validate_chore_fields(req)
    existing = storage.get_chore(chore_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Chore not found")
    patch = {'title': req.title.strip(), 'emoji': _clean_emoji(req.emoji),
             'description': req.description or '',
             'points': int(req.points), 'recurrence': req.recurrence,
             'eligible_member_ids': req.eligible_member_ids or []}
    # Only touch the lifecycle when the OWNER actually changed — editing the
    # title of a chore somebody has already finished must not reset it.
    if (req.owner or None) != (existing.get('owner') or None):
        patch.update(_owned_chore_fields(req.owner))
    if not storage.update_chore(chore_id, patch):
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

def _chore_claimant(holder_id: str):
    """Who is taking this chore — a member, or an outside hand.

    An outside hand is not a new concept here: an adult already claims a chore
    and earns nothing (`verify_chore` awards points only when the claimant's
    role is `child`), and a contact is the same shape — somebody who does the
    work and is not in the points economy. So they widen the id space and
    change no rule. Returns (name, is_assist) or (None, False) if the id is
    nobody at all."""
    if _assist_svc.is_assist_id(holder_id):
        c = storage.get_assist_contact(_assist_svc.contact_id(holder_id))
        return ((c or {}).get('name'), True) if c else (None, False)
    m = storage.get_member(holder_id)
    if not m:
        return (None, False)
    if m.get('role') == 'helper':
        raise HTTPException(status_code=403, detail="Helpers don't do family chores")
    return (m.get('name'), False)

@app.post("/api/chores/{chore_id}/claim")
def claim_chore_endpoint(chore_id: str, req: ChoreMemberRequest):
    name, _is_assist = _chore_claimant(req.member_id)
    if not name:
        raise HTTPException(status_code=404, detail="Member not found")
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

class ChoreAssignRequest(BaseModel):
    member_id: Optional[str] = None    # None/empty puts it back in the pot
    assigned_by: str                   # the parent doing the assigning

@app.post("/api/chores/{chore_id}/assign")
def assign_chore_endpoint(chore_id: str, req: ChoreAssignRequest):
    """Give THIS occurrence to somebody. The other half of the pot.

    Work that has to happen every day but is only sometimes done by the same
    person — the dishes, when the helper is in twice a week — cannot be owned
    by her, or it would come back to her on the four days she is not there.
    So it stays ownerless in the pot, and a parent hands out each night's.
    Cleared when the chore recurs, so tomorrow's is up for grabs again.

    Assigning is claiming on somebody's behalf, so it reuses the lifecycle
    exactly; the only new fact is WHO decided, which is what stops the holder
    handing it straight back."""
    chore = storage.get_chore(chore_id)
    if not chore:
        raise HTTPException(status_code=404, detail="Chore not found")
    if chore.get('owner'):
        raise HTTPException(status_code=409,
                            detail="That chore has an owner — change the owner instead")
    if not req.member_id:
        if chore.get('state') not in ('open', 'claimed'):
            raise HTTPException(status_code=409, detail="That chore isn't in play")
        storage.update_chore(chore_id, {'state': 'open', 'claimed_by': None,
                                        'claimed_at': None, 'assigned_by': None})
        return storage.get_chore(chore_id)
    name, _is_assist = _chore_claimant(req.member_id)
    if not name:
        raise HTTPException(status_code=404, detail="Nobody by that id")
    eligible = chore.get('eligible_member_ids') or []
    if eligible and req.member_id not in eligible:
        raise HTTPException(status_code=403, detail=f"{name} isn't on this chore")
    if chore.get('state') not in ('open', 'claimed'):
        raise HTTPException(status_code=409, detail="That chore isn't waiting to be done")
    storage.update_chore(chore_id, {'state': 'claimed', 'claimed_by': req.member_id,
                                    'claimed_at': time.time(),
                                    'assigned_by': req.assigned_by,
                                    'rejected_reason': None})
    return storage.get_chore(chore_id)

@app.post("/api/chores/{chore_id}/record")
def record_chore_endpoint(chore_id: str, req: ChoreMemberRequest,
                          background_tasks: BackgroundTasks):
    """"Maddie did the dishes" — claim and finish in one call.

    An outside hand has no login by definition, so the claim → done pair a kid
    walks through by tapping cannot be walked by them. A parent records it
    instead, in one action, and the chore lands in the SAME `done` state
    awaiting the same verification — which is what reopens it on its cadence.
    Works for a member too: an adult who just did it without claiming first
    should not have to pretend they did."""
    name, _is_assist = _chore_claimant(req.member_id)
    if not name:
        raise HTTPException(status_code=404, detail="Nobody by that id")
    chore = storage.get_chore(chore_id)
    if not chore:
        raise HTTPException(status_code=404, detail="Chore not found")
    eligible = chore.get('eligible_member_ids') or []
    if eligible and req.member_id not in eligible:
        raise HTTPException(status_code=403, detail=f"{name} isn't on this chore")
    if chore.get('state') not in ('open', 'claimed'):
        raise HTTPException(status_code=409, detail="That chore isn't waiting to be done")
    storage.update_chore(chore_id, {'state': 'done', 'claimed_by': req.member_id,
                                    'claimed_at': time.time(), 'done_at': time.time(),
                                    'rejected_reason': None})
    chore = storage.get_chore(chore_id)
    background_tasks.add_task(_notify_chore_event, 'done', chore, None)
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
    from services import status_tiers
    balances = storage.get_all_point_balances()
    for b in balances:
        b['status'] = status_tiers.compute_member_status(b['member_id'], 'chore')
    return balances

@app.get("/api/status-tiers")
def get_status_tiers_endpoint(kind: str = "chore"):
    """The effective ladder (configured or defaults) for kind=chore|routine."""
    from services import status_tiers
    return status_tiers.get_tiers(kind)

class StatusTiersUpdate(BaseModel):
    tiers: List[StatusTier]

@app.put("/api/status-tiers")
def put_status_tiers_endpoint(req: StatusTiersUpdate, kind: str = "chore"):
    # Stored ascending by threshold so "highest reached wins" is unambiguous.
    # patch_settings (not update_settings): tiers never affect the solver.
    k = 'routine' if kind == 'routine' else 'chore'
    key = 'routine_status_tiers' if k == 'routine' else 'chore_status_tiers'
    tiers = sorted((t.model_dump() for t in req.tiers), key=lambda t: t['threshold'])
    storage.patch_settings({key: tiers})
    return {'status': 'ok', 'tiers': tiers}

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
        'spendable': storage.get_spendable_points(member_id),
        'pledged': sum(c['amount'] for c in storage.get_pool_contributions(member_id=member_id)),
        'ledger': storage.get_points_ledger(member_id, limit=limit),
    }

# --- Routines API (personal daily checklists; no points, streaks instead) ---

class RoutineRequest(BaseModel):
    member_id: str
    title: str
    emoji: Optional[str] = None
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
                       emoji=_clean_emoji(req.emoji),
                       time_of_day=req.time_of_day or None,
                       days_of_week=sorted(set(req.days_of_week or []))).model_dump()
    storage.add_routine(item)
    return item

@app.put("/api/routines/{routine_id}")
def edit_routine(routine_id: str, req: RoutineRequest):
    _validate_routine(req)
    if not storage.update_routine(routine_id, {
            'member_id': req.member_id, 'title': req.title.strip(),
            'emoji': _clean_emoji(req.emoji),
            'time_of_day': req.time_of_day or None,
            'days_of_week': sorted(set(req.days_of_week or []))}):
        raise HTTPException(status_code=404, detail="Routine not found")
    return {"status": "updated"}

@app.delete("/api/routines/{routine_id}")
def remove_routine(routine_id: str):
    storage.delete_routine(routine_id)
    return {"status": "deleted"}

class RoutineCopyRequest(BaseModel):
    from_member_id: str
    to_member_id: str

@app.post("/api/routines/copy")
def copy_routines(req: RoutineCopyRequest):
    """Copy one member's routine onto another — the kids' routines are mostly
    the same, so set one up, copy it, edit the differences. MERGE semantics:
    an item is skipped when the target already has one with the same title
    AND time of day, so copying onto a half-built routine tops it up rather
    than doubling it, and copying twice is harmless.

    Two skip tests, and LINEAGE goes first: every copy records which source
    item it came from (`copied_from`), so a copy the target has since
    retimed or renamed still says "I am that item" and a re-copy leaves it
    alone — content matching alone re-imported the original the moment the
    copy was edited, which was the balance the family kept running into.
    The (title, time-of-day) content key remains as the second test, for
    items that match hand-made ones; the day mask stays out of it (differing
    masks are per-kid tweaks of the same item). Deleting a copied item and
    re-copying DOES bring it back — re-copy is an explicit "make it like
    theirs again". Checks/streaks never copy — they are the target kid's
    own history."""
    from models.schemas import RoutineItem
    if req.from_member_id == req.to_member_id:
        raise HTTPException(status_code=400, detail="Pick two different people")
    for mid in (req.from_member_id, req.to_member_id):
        if not storage.get_member(mid):
            raise HTTPException(status_code=404, detail="Member not found")
    src = storage.get_routines(req.from_member_id)
    if not src:
        raise HTTPException(status_code=400, detail="Nothing to copy — that routine is empty")
    def _key(r):
        title = (r.get('title') or '').strip().casefold()
        return (title, r.get('time_of_day') or '') if title else None
    target = storage.get_routines(req.to_member_id)
    have = {_key(r) for r in target} - {None}
    lineage = {r.get('copied_from') for r in target if r.get('copied_from')}
    created = skipped = 0
    for r in src:
        key = _key(r)
        if not key or r.get('id') in lineage or key in have:
            skipped += 1
            continue
        have.add(key)
        storage.add_routine(RoutineItem(
            member_id=req.to_member_id, title=r['title'],
            emoji=r.get('emoji') or None,
            time_of_day=r.get('time_of_day') or None,
            days_of_week=sorted(set(r.get('days_of_week') or [])),
            copied_from=r.get('id')).model_dump())
        created += 1
    return {"created": created, "skipped": skipped}

@app.get("/api/routines/day")
def routines_day(member_id: str, date: Optional[str] = None):
    import datetime as _dt
    from services import status_tiers
    date_str = date or _dt.date.today().isoformat()
    if not storage.get_member(member_id):
        raise HTTPException(status_code=404, detail="Member not found")
    return {
        'date': date_str,
        'items': storage.routines_for_day(member_id, date_str),
        'streak': storage.compute_streak(member_id),
        'status': status_tiers.compute_member_status(member_id, 'routine'),
    }

@app.get("/api/routines/streaks")
def routines_streaks():
    """Per-member streak summary for every member with routine items —
    feeds the routines page header chips and the kiosk streak board."""
    from services import status_tiers
    member_ids = {r['member_id'] for r in storage.get_routines()}
    out = []
    for m in storage.get_all_members():
        if m['id'] not in member_ids:
            continue
        out.append({
            'member_id': m['id'], 'name': m.get('name'),
            'color_code': m.get('color_code'), 'avatar': m.get('avatar'),
            'image': m.get('image'),
            'streak': storage.compute_streak(m['id']),
            'status': status_tiers.compute_member_status(m['id'], 'routine'),
        })
    out.sort(key=lambda x: (-x['streak']['current'], x['name'] or ''))
    return out

# --- Prep kits (packing lists matched to events by title keywords) ---

class PrepKitRequest(BaseModel):
    name: str
    keywords: List[str] = []
    items: List[str] = []
    enabled: bool = True
    keywords_match_all: bool = False
    passenger_ids: List[str] = []
    passengers_match_all: bool = False
    days_of_week: List[int] = []
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None

def _validate_prep_kit(req: PrepKitRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Kit name is required")
    if not [i for i in req.items if i.strip()]:
        raise HTTPException(status_code=400, detail="At least one item is required")
    # Same rule as rule-filters: with no criterion at all, nothing can match
    # (does_event_match_rule requires at least one satisfied criterion).
    if not ([k for k in req.keywords if k.strip()] or req.passenger_ids
            or req.days_of_week or (req.location or '').strip()
            or req.time_start or req.time_end or req.start_date or req.end_date):
        raise HTTPException(status_code=400,
                            detail="Add at least one matching criterion (keyword, passenger, day, time, date, or location)")

def _prep_kit_fields(req: PrepKitRequest) -> dict:
    return {'name': req.name.strip(),
            'items': [i.strip() for i in req.items if i.strip()],
            'enabled': req.enabled,
            'keywords': [k.strip().lower() for k in req.keywords if k.strip()],
            'keywords_match_all': req.keywords_match_all,
            'passenger_ids': [str(p) for p in req.passenger_ids],
            'passengers_match_all': req.passengers_match_all,
            'days_of_week': sorted({int(d) for d in req.days_of_week}),
            'time_start': req.time_start or None,
            'time_end': req.time_end or None,
            'start_date': req.start_date or None,
            'end_date': req.end_date or None,
            'location': (req.location or '').strip() or None}

@app.get("/api/prep-kits")
def list_prep_kits():
    kits = storage.get_prep_kits()
    kits.sort(key=lambda k: (k.get('name') or '').lower())
    return kits

@app.post("/api/prep-kits")
def create_prep_kit(req: PrepKitRequest):
    from models.schemas import PrepKit
    _validate_prep_kit(req)
    kit = PrepKit(**_prep_kit_fields(req)).model_dump()
    storage.add_prep_kit(kit)
    return kit

@app.put("/api/prep-kits/{kit_id}")
def edit_prep_kit(kit_id: str, req: PrepKitRequest):
    _validate_prep_kit(req)
    if not storage.update_prep_kit(kit_id, _prep_kit_fields(req)):
        raise HTTPException(status_code=404, detail="Kit not found")
    return {"status": "updated"}

@app.delete("/api/prep-kits/{kit_id}")
def remove_prep_kit(kit_id: str):
    storage.delete_prep_kit(kit_id)
    return {"status": "deleted"}

@app.get("/api/prep-kits/matches")
def prep_kit_matches():
    """Which upcoming schedule-cache events each kit matches — the same
    visibility routing rules get, so a kit's filters are verifiable instead
    of guessed. Split dropoff/pickup variants collapse to one entry."""
    from services import prep_kits
    kits = storage.get_prep_kits()
    cache = storage.get_cached_schedule() or {}
    pax = prep_kits.passenger_objs()
    out = {k['id']: [] for k in kits}
    seen = {k['id']: set() for k in kits}
    events = sorted(cache.get('events', []), key=lambda e: e.get('start') or '')
    for ev in events:
        if ev.get('event_type') == 'errand' or ev.get('trip_suppressed'):
            continue
        parent_id = str(ev.get('id', ''))
        for suffix in ('_dropoff', '_pickup'):
            if parent_id.endswith(suffix):
                parent_id = parent_id[:-len(suffix)]
        for kit in prep_kits.match_kits_for_event(ev, kits, pax):
            if parent_id in seen[kit['id']] or len(out[kit['id']]) >= 20:
                continue
            seen[kit['id']].add(parent_id)
            out[kit['id']].append({'title': ev.get('title'), 'start': ev.get('start')})
    return out

@app.post("/api/prep-kits/suggest")
def suggest_prep_kits():
    """One LLM request over upcoming event titles -> proposed kits for review.
    Nothing is saved here — the client edits and POSTs the ones it keeps."""
    from services import prep_kits
    cache = storage.get_cached_schedule() or {}
    titles = {e.get('title') for e in cache.get('events', [])
              if e.get('title') and e.get('event_type') != 'errand'
              and not e.get('trip_suppressed')}
    if not titles:
        raise HTTPException(status_code=400, detail="No upcoming events to analyze yet")
    try:
        kits = prep_kits.suggest_kits(sorted(titles))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"kits": kits}

class RoutineCheckRequest(BaseModel):
    member_id: str
    date: Optional[str] = None
    checked: bool = True

@app.post("/api/routines/{routine_id}/check")
def check_routine(routine_id: str, req: RoutineCheckRequest):
    import datetime as _dt
    from services import status_tiers
    date_str = req.date or _dt.date.today().isoformat()
    if not storage.set_routine_check(routine_id, req.member_id, date_str, req.checked):
        raise HTTPException(status_code=403, detail="Not your routine")
    return {'status': 'ok', 'streak': storage.compute_streak(req.member_id),
            'tier_status': status_tiers.compute_member_status(req.member_id, 'routine')}

# --- Rewards + redemptions API ---

class RewardRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    cost: int = 50
    pooled: bool = False
    min_share: int = 0

@app.get("/api/rewards")
def list_rewards():
    rewards = storage.get_rewards()
    rewards.sort(key=lambda r: r.get('cost', 0))
    for r in rewards:
        if r.get('pooled'):
            r['pool'] = storage.get_pool_status(r)
    return rewards

@app.post("/api/rewards")
def create_reward(req: RewardRequest):
    from models.schemas import Reward
    if not (req.title or '').strip():
        raise HTTPException(status_code=400, detail="Title required")
    if not (1 <= int(req.cost) <= 100000):
        raise HTTPException(status_code=400, detail="Cost must be positive")
    if req.min_share < 0 or (req.pooled and req.min_share > int(req.cost)):
        raise HTTPException(status_code=400, detail="Minimum share must be between 0 and the cost")
    reward = Reward(title=req.title.strip(), description=req.description or '',
                    cost=int(req.cost), pooled=bool(req.pooled),
                    min_share=int(req.min_share) if req.pooled else 0).model_dump()
    storage.add_reward(reward)
    return reward

@app.put("/api/rewards/{reward_id}")
def edit_reward(reward_id: str, req: RewardRequest):
    if req.min_share < 0 or (req.pooled and req.min_share > int(req.cost)):
        raise HTTPException(status_code=400, detail="Minimum share must be between 0 and the cost")
    if not storage.update_reward(reward_id, {
            'title': req.title.strip(), 'description': req.description or '',
            'cost': int(req.cost), 'pooled': bool(req.pooled),
            'min_share': int(req.min_share) if req.pooled else 0}):
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
    if result == 'pooled':
        raise HTTPException(status_code=409, detail="This is a family goal — chip in points instead")
    if result == 'insufficient':
        raise HTTPException(status_code=409, detail="Not enough points (pending requests and pledges count)")
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

# --- Pooled rewards (family goals) ---
# Kids pledge points toward one shared reward; a pledge is a hold (nothing
# hits the ledger) until a parent grants the funded pool. Contribution
# notifications go to the OTHER children on purpose — peer visibility is
# the motivator — and to parents only when the pool fills up.

class PoolContributeRequest(BaseModel):
    member_id: str
    amount: int

def _notify_pool_contribution(reward: dict, contributor: dict, amount: int):
    """Shared by the contribute endpoint and the agent tool."""
    pool = storage.get_pool_status(reward)
    body = (f"{contributor.get('name')} chipped in {amount} ⭐ toward "
            f"{reward.get('title')} — {pool['pledged']}/{pool['cost']}")
    for m in storage.get_all_members():
        if m.get('role') == 'child' and m['id'] != contributor['id']:
            _notify_member_lanes(m, 'Family goal 💫', body, '/app?view=chores')
        elif m.get('role') == 'parent' and pool['funded']:
            _notify_member_lanes(m, 'Family goal funded 🎉',
                                 f"{reward.get('title')} is fully funded — grant it in the app",
                                 '/app?view=chores')

@app.post("/api/rewards/{reward_id}/contribute")
def contribute_to_pool_endpoint(reward_id: str, req: PoolContributeRequest,
                                background_tasks: BackgroundTasks):
    member = storage.get_member(req.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.get('role') != 'child':
        raise HTTPException(status_code=403, detail="Only children chip in points")
    result, pledged = storage.contribute_to_pool(reward_id, req.member_id, req.amount)
    if result == 'missing':
        raise HTTPException(status_code=404, detail="Reward not found")
    if result == 'not_pooled':
        raise HTTPException(status_code=409, detail="That reward isn't a family goal")
    if result == 'invalid':
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if result == 'full':
        raise HTTPException(status_code=409, detail="This goal is already fully funded")
    if result == 'insufficient':
        raise HTTPException(status_code=409, detail="Not enough spendable points (pending requests and pledges count)")
    reward = next((r for r in storage.get_rewards() if r['id'] == reward_id), {})
    background_tasks.add_task(_notify_pool_contribution, reward, member, pledged)
    return {"status": "pledged", "amount": pledged,
            "pool": storage.get_pool_status(reward)}

@app.post("/api/rewards/{reward_id}/withdraw")
def withdraw_pool_pledge_endpoint(reward_id: str, req: ChoreMemberRequest):
    released = storage.withdraw_pool_pledge(reward_id, req.member_id)
    if not released:
        raise HTTPException(status_code=404, detail="No pledge to withdraw")
    reward = next((r for r in storage.get_rewards() if r['id'] == reward_id), None)
    return {"status": "withdrawn", "amount": released,
            "pool": storage.get_pool_status(reward) if reward else None}

class PoolDecision(BaseModel):
    approve: bool
    force: bool = False  # grant despite children short of min_share

@app.post("/api/rewards/{reward_id}/pool/decide")
def decide_pool_endpoint(reward_id: str, req: PoolDecision,
                         background_tasks: BackgroundTasks,
                         x_member_token: Optional[str] = Header(None)):
    parent = require_parent_token(x_member_token)
    reward = next((r for r in storage.get_rewards() if r['id'] == reward_id), None)
    if not reward or not reward.get('pooled'):
        raise HTTPException(status_code=404, detail="Family goal not found")
    if not req.approve:
        contribs = storage.get_pool_contributions(reward_id=reward_id)
        storage.clear_pool(reward_id)
        for c in contribs:
            kid = storage.get_member(c['member_id'])
            if kid:
                background_tasks.add_task(
                    _notify_member_lanes, kid, 'Family goal called off',
                    f"{reward.get('title')} — your {c['amount']} ⭐ pledge is back in your balance",
                    '/app?view=chores')
        return {"status": "cleared", "released": len(contribs)}
    redemption, err = storage.grant_pool(reward_id, parent['id'], force=req.force)
    if err == 'unfunded':
        raise HTTPException(status_code=409, detail="Not fully funded yet")
    if err == 'short':
        pool = storage.get_pool_status(reward)
        names = ', '.join(n for n in pool['short'] if n)
        raise HTTPException(status_code=409,
                            detail=f"Below the {pool['min_share']}-point minimum share: {names}")
    if err:
        raise HTTPException(status_code=404, detail="Family goal not found")
    for c in redemption['contributions']:
        kid = storage.get_member(c['member_id'])
        if kid:
            background_tasks.add_task(
                _notify_member_lanes, kid, 'Family goal granted 🎉',
                f"{redemption['reward_title']} is happening! -{c['amount']} ⭐",
                '/app?view=chores')
    return redemption

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
    car_assignments = dict(sched.get('car_assignments', {}) or {})
    _cars_by_id = {c.get('id'): c for c in storage.get_all_cars()}

    def _ride_car(ev_id):
        c = _cars_by_id.get(car_assignments.get(ev_id))
        if not c:
            return None
        return {'id': c.get('id'), 'name': c.get('name'), 'icon': c.get('icon'), 'image': c.get('image')}

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
                'image': m.get('image'),
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
        cals = set(str(c) for c in (ev.get('calendar_ids') or []))
        title_l = (ev.get('title') or '').lower()
        # Four-way binding. The solver REPLACES a matched event's cached
        # calendar_ids with the RESOLVED passenger ids (event-config
        # attendance included — configs aren't rules, so they never appear
        # in matched_rules), making passenger-id membership the
        # authoritative post-solve check; calendar/hashtag/rule checks
        # cover events the solver didn't rewrite.
        bound = bool(cals & p_cals) \
            or (p_id and str(p_id) in cals) \
            or any(t in title_l for t in p_tags) \
            or _rule_bound({ev_id, parent_id, rule_base})
        if not bound:
            continue
        matched.append((ev, ev_id, parent_id))

    from services import prep_kits as _prep
    from services.optional_events import decision_for as _opt_decision
    _kits = storage.get_prep_kits()
    _pax = _prep.passenger_objs()

    # Outside hands (load arc A1). "Riding with Emma's mom" is exactly the
    # certainty the kid arc exists to sell, and it was invisible: a
    # carpool-covered ride had no driver, so the digest simply said nothing.
    _assist_map = dict(sched.get('assist_assignments', {}))
    _assist_by_id = {c['id']: c for c in (sched.get('assist_contacts')
                                          or storage.get_assist_contacts(include_inactive=True))}

    def _assist_for(ev_id):
        c = _assist_by_id.get(_assist_map.get(ev_id))
        if not c:
            return None
        # The label the family actually says out loud comes first: a child
        # knows "Emma's mom" and may not know her name.
        return {'id': c['id'], 'name': c.get('name'),
                'label': c.get('relation_label') or c.get('name'),
                'phone': c.get('phone') or ''}

    def _ride(ev, ev_id, legs=None):
        return {
            'assist': _assist_for(ev_id),
            'id': ev.get('id'),
            'title': ev.get('title'),
            'event_type': ev.get('event_type', 'standard'),
            'start': ev.get('start'),
            'end': ev.get('end'),
            # A background trip's slice `start`/`end` are THIS DAY's, so
            # without these a ride knows it is part of a trip and nothing
            # about which part. The whole point of stamping the original's
            # dates onto the slice was to get them here; this dict is a
            # whitelist, so they were being dropped one step before the only
            # code that wanted them, and every reader downstream saw a trip
            # with no span no matter how often the schedule refreshed.
            'span_start': ev.get('span_start'),
            'span_end': ev.get('span_end'),
            'location': ev.get('location'),
            'driver': _driver_member(assignments.get(ev_id)),
            'car': _ride_car(ev_id),
            'status': status_by_event.get(ev_id),
            'legs': legs or [],
            'prep': _prep.items_for_event(ev, _kits, _pax),
            # Optional events (event config): the card softens its voice — an
            # optional ride without a driver was skipped, not failed. The
            # decision is read LIVE (not the cached stamp): the button's
            # re-solve runs in the background, and the card must show the
            # choice the moment it was made, not a solve later.
            'optional': bool((ev.get('app_config') or {}).get('is_optional')),
            'optional_decision': (_opt_decision(ev)
                                  if (ev.get('app_config') or {}).get('is_optional')
                                  else None),
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
                'car': _ride_car(ev_id),
                'status': status_by_event.get(ev_id),
            })
        ride = _ride(base[0], base[1], legs)
        if any(l['status'] == 'in_progress' for l in legs):
            ride['status'] = 'in_progress'
        elif legs and all(l['status'] == 'completed' for l in legs):
            ride['status'] = 'completed'
        rides.append(ride)
    rides.sort(key=lambda r: r.get('start') or '')

    # K5: morning launch — when the day's FIRST ride's driver starts from
    # home (the solver's initial edge covers exactly that case), surface the
    # honest leave-by time: start − travel − driver buffer. No edge (driver
    # mid-chain, ghost suggestion, unknown route) -> no line; the ride card
    # already shows its start time.
    launch = None
    if rides:
        first = rides[0]
        candidates = [str(first.get('id'))]
        if first.get('legs'):
            candidates.append(f"{first.get('id')}_dropoff")
        # The arithmetic moved to services/leave_by, which the wall panel's
        # hero now shares — one definition of "leave by", or the kitchen and
        # the phone eventually disagree about it. `from_home_only` keeps this
        # caller's meaning exactly: a child reading "leave by 4:20" is being
        # told when to put their shoes on, so a driver arriving from somewhere
        # else does not count.
        from services import leave_by as leave_by_svc
        for ev_key in candidates:
            d_id = assignments.get(ev_key)
            if not d_id:
                continue
            try:
                start_dt = _dt.datetime.fromisoformat(first['start'])
            except (ValueError, TypeError):
                break
            # live: today's day-of traffic when this is TODAY's page; the
            # overlay itself refuses other days, so the tomorrow digest
            # reading through here still gets the static plan.
            found = leave_by_svc.for_run(sched, d_id, ev_key, start_dt,
                                         from_home_only=True, live=True)
            if not found:
                continue
            launch = {**found, 'title': first.get('title'),
                      'driver': _driver_member(d_id)}
            break

    # Bus arc B1: bus kids get a launch line too — on school mornings the
    # bus IS the first ride. Static member stop time is the baseline, the
    # live HCTB estimate (via the HA bridge) wins when the bus is running.
    # Skipped whenever a morning car ride covers the school run.
    if launch is None and member.get('role') == 'child':
        from services import bus
        launch = bus.morning_launch(member, date_str, rides)

    # K4a: the kid's school/deadline list — open tasks due within 7 days of
    # the viewed date, plus overdue (worded gently, shown in place, never
    # pushed). Empty for members with no tasks (adults).
    ref = _dt.date.fromisoformat(date_str)
    due_soon = []
    for t in storage.get_kid_tasks(member_id):
        try:
            due = _dt.date.fromisoformat(t.get('due_date') or '')
        except ValueError:
            continue
        if due > ref + _dt.timedelta(days=7):
            continue
        due_soon.append({'id': t['id'], 'title': t.get('title'),
                         'kind': t.get('kind') or 'other',
                         'emoji': _TASK_EMOJI.get(t.get('kind'), '📌'),
                         'due_date': t.get('due_date'), 'overdue': due < ref,
                         'label': _task_due_label(due, ref)})

    # Presence & Status P1: active family statuses for the viewed date ride
    # every member's day payload — the My Day banner is how a kid (or the
    # co-parent) sees "what today is" without asking.
    from services import status_protocols
    try:
        status_days = status_protocols.active_statuses(date_str)
    except Exception as se:
        print(f"Status resolve failed for {date_str}: {se}")
        status_days = []

    return {
        'member_id': member_id,
        'name': member.get('name'),
        'date': date_str,
        'rides': rides,
        'due_soon': due_soon,
        'launch': launch,
        'status_days': status_days,
    }

# --- Kid tasks (school/deadline list, kid-support arc K4a) ---

_TASK_EMOJI = {'homework': '📚', 'test': '📝', 'project': '📐', 'bring': '🎒', 'other': '📌'}

def _task_due_label(due, ref):
    """Gentle due wording relative to ref: 'due today/tomorrow', a weekday
    for later, 'still open (was due Fri)' for overdue — never shaming."""
    from services import family_digest
    if due < ref:
        return f"still open (was due {due.strftime('%a')})"
    lbl = family_digest.day_label(due)
    return "due " + (lbl.lower() if lbl in ("Today", "Tomorrow") else due.strftime('%A'))

def _task_line(task, ref):
    import datetime as _dt
    emoji = _TASK_EMOJI.get(task.get('kind'), '📌')
    title = task.get('title') or 'Task'
    try:
        due = _dt.date.fromisoformat(task.get('due_date') or '')
    except ValueError:
        return f"{emoji} {title}"
    return f"{emoji} {title} — {_task_due_label(due, ref)}"

class KidTaskRequest(BaseModel):
    member_id: str
    title: str
    due_date: str            # YYYY-MM-DD
    kind: str = 'other'      # homework | test | project | bring | other
    notes: Optional[str] = ""

class KidTaskCompleteRequest(BaseModel):
    member_id: Optional[str] = None   # per-action identity (PWA pattern)
    done: bool = True

def _validate_kid_task(req: KidTaskRequest):
    import datetime as _dt
    if not (req.title or '').strip():
        raise HTTPException(status_code=400, detail="Task needs a title")
    try:
        _dt.date.fromisoformat(req.due_date)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="due_date must be YYYY-MM-DD")
    member = storage.get_member(req.member_id)
    if not member or member.get('role') != 'child':
        raise HTTPException(status_code=400, detail="Tasks belong to a child member")

@app.get("/api/kid-tasks")
def list_kid_tasks(member_id: Optional[str] = None, include_done: bool = False):
    return storage.get_kid_tasks(member_id, include_done)

@app.post("/api/kid-tasks")
def create_kid_task(req: KidTaskRequest):
    from models.schemas import KidTask
    _validate_kid_task(req)
    task = KidTask(member_id=req.member_id, title=req.title.strip(),
                   due_date=req.due_date,
                   kind=req.kind if req.kind in _TASK_EMOJI else 'other',
                   notes=req.notes or "").model_dump()
    storage.add_kid_task(task)
    return task

@app.put("/api/kid-tasks/{task_id}")
def edit_kid_task(task_id: str, req: KidTaskRequest):
    _validate_kid_task(req)
    if not storage.update_kid_task(task_id, {
            'title': req.title.strip(), 'due_date': req.due_date,
            'kind': req.kind if req.kind in _TASK_EMOJI else 'other',
            'notes': req.notes or ""}):
        raise HTTPException(status_code=404, detail="Task not found")
    return storage.get_kid_task(task_id)

@app.delete("/api/kid-tasks/{task_id}")
def remove_kid_task(task_id: str):
    storage.delete_kid_task(task_id)
    return {"status": "ok"}

@app.post("/api/kid-tasks/{task_id}/complete")
def complete_kid_task_api(task_id: str, req: KidTaskCompleteRequest):
    task = storage.get_kid_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if req.member_id:
        actor = storage.get_member(req.member_id)
        if actor and actor.get('role') == 'child' and actor['id'] != task['member_id']:
            raise HTTPException(status_code=403, detail="You can only check off your own tasks")
    return storage.complete_kid_task(task_id, req.done)

# --- Shopping lists (meals & provisioning arc M1) -----------------------------
# Design contract (docs/meal_design.md §M1): there is NO whole-list write
# endpoint for items. Every item mutation is a per-item PATCH so two people at
# the store — or one adding while another shops — cannot clobber each other.
# Adds are direct and ungated regardless of who is asking: a list item costs
# the family nothing, so the proposal queue would be friction with no gate.

class ShoppingListRequest(BaseModel):
    name: str = "Groceries"
    store: Optional[str] = None
    errand_tag: Optional[str] = None
    is_default: bool = False

class ShoppingItemRequest(BaseModel):
    name: str
    qty: Optional[str] = None
    note: Optional[str] = None
    list_id: Optional[str] = None      # omitted -> the default list
    added_by: Optional[str] = None     # member id (attribution only)
    added_via: str = 'manual'

class ShoppingItemPatch(BaseModel):
    # Every field optional: a PATCH carries only what this caller changed.
    name: Optional[str] = None
    qty: Optional[str] = None
    note: Optional[str] = None
    is_checked: Optional[bool] = None
    member_id: Optional[str] = None    # who tapped (PWA per-action identity)

_SHOPPING_VIA = {'manual', 'voice', 'photo', 'meal', 'barcode'}

def _touch_stream():
    """Bump the SSE clock so open list views pull the delta."""
    global LAST_UPDATE_TIME
    LAST_UPDATE_TIME = time.time()

@app.get("/api/shopping/lists")
def list_shopping_lists():
    storage.ensure_default_shopping_list()
    lists = storage.get_shopping_lists()
    for l in lists:
        items = storage.get_shopping_items(l['id'])
        l['open_count'] = sum(1 for i in items if not i.get('is_checked'))
        l['checked_count'] = len(items) - l['open_count']
    return lists

@app.post("/api/shopping/lists")
def create_shopping_list(req: ShoppingListRequest):
    from models.schemas import ShoppingList
    if not (req.name or '').strip():
        raise HTTPException(status_code=400, detail="A list needs a name")
    lst = ShoppingList(name=req.name.strip(), store=(req.store or '').strip() or None,
                       errand_tag=(req.errand_tag or '').strip().lower() or None,
                       is_default=req.is_default).model_dump()
    if req.is_default:
        for other in storage.get_shopping_lists():
            if other.get('is_default'):
                storage.update_shopping_list(other['id'], {'is_default': False})
    storage.add_shopping_list(lst)
    _touch_stream()
    return lst

@app.put("/api/shopping/lists/{list_id}")
def edit_shopping_list(list_id: str, req: ShoppingListRequest):
    if req.is_default:
        for other in storage.get_shopping_lists():
            if other['id'] != list_id and other.get('is_default'):
                storage.update_shopping_list(other['id'], {'is_default': False})
    if not storage.update_shopping_list(list_id, {
            'name': (req.name or '').strip() or 'Groceries',
            'store': (req.store or '').strip() or None,
            'errand_tag': (req.errand_tag or '').strip().lower() or None,
            'is_default': req.is_default}):
        raise HTTPException(status_code=404, detail="List not found")
    _touch_stream()
    return storage.get_shopping_list(list_id)

@app.delete("/api/shopping/lists/{list_id}")
def remove_shopping_list(list_id: str):
    storage.delete_shopping_list(list_id)
    _touch_stream()
    return {"status": "ok"}

@app.get("/api/shopping/items")
def list_shopping_items(list_id: Optional[str] = None, include_checked: bool = True):
    if not list_id:
        list_id = storage.ensure_default_shopping_list()['id']
    return storage.get_shopping_items(list_id, include_checked)

@app.get("/api/shopping/runs")
def shopping_item_runs(list_id: Optional[str] = None):
    """The open list, split by which shop run each item is for — so a mid-week
    dash for tonight's re-planned dinner does not arrive carrying all of
    Saturday, and so the rest is still one tap away while you are standing in
    a store."""
    from services import shopping as _shop
    return _shop.item_runs(list_id or storage.ensure_default_shopping_list()['id'])

@app.post("/api/shopping/items")
def create_shopping_item(req: ShoppingItemRequest):
    from models.schemas import ShoppingItem
    name = (req.name or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="What should go on the list?")
    list_id = req.list_id or storage.ensure_default_shopping_list()['id']
    if not storage.get_shopping_list(list_id):
        raise HTTPException(status_code=404, detail="List not found")
    # Saying "milk" twice must not put milk on the list twice. A re-add after
    # checking off IS a new need, so only unchecked rows dedupe.
    existing = storage.find_open_shopping_item(list_id, name)
    if existing:
        patch = {}
        if req.qty and req.qty != existing.get('qty'):
            patch['qty'] = req.qty
        if req.note and req.note != existing.get('note'):
            patch['note'] = req.note
        if patch:
            storage.update_shopping_item(existing['id'], patch)
            existing.update(patch)
        existing['deduped'] = True
        _touch_stream()
        return existing
    item = ShoppingItem(list_id=list_id, name=name,
                        qty=(req.qty or '').strip() or None,
                        note=(req.note or '').strip() or None,
                        added_by=req.added_by,
                        added_via=req.added_via if req.added_via in _SHOPPING_VIA
                        else 'manual').model_dump()
    storage.add_shopping_item(item)
    _touch_stream()
    return item

@app.patch("/api/shopping/items/{item_id}")
def patch_shopping_item(item_id: str, req: ShoppingItemPatch):
    """The only item write path. Sends only changed fields, so a check tap and
    a qty edit on different items never race — and re-checking an already
    checked item is an idempotent no-op rather than an error."""
    item = storage.get_shopping_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    patch = {}
    if req.name is not None and req.name.strip():
        patch['name'] = req.name.strip()
    if req.qty is not None:
        patch['qty'] = req.qty.strip() or None
    if req.note is not None:
        patch['note'] = req.note.strip() or None
    if patch:
        storage.update_shopping_item(item_id, patch)
    if req.is_checked is not None:
        storage.check_shopping_item(item_id, req.is_checked, req.member_id)
    _touch_stream()
    return storage.get_shopping_item(item_id)

@app.delete("/api/shopping/items/{item_id}")
def remove_shopping_item(item_id: str):
    storage.delete_shopping_item(item_id)
    _touch_stream()
    return {"status": "ok"}

@app.post("/api/shopping/lists/{list_id}/clear-checked")
def clear_checked_shopping(list_id: str):
    n = storage.clear_checked_shopping_items(list_id)
    _touch_stream()
    return {"status": "ok", "cleared": n}

@app.get("/api/meals/plan")
def meals_plan(date: Optional[str] = None, meal: str = 'dinner'):
    """The day's eating plan (M2): per-person slots with a modality, the
    household's sittings, the cook window, and — first-class — who has no gap
    to eat at all. Read-only over solver output; writes nothing."""
    import datetime as _dt
    from services import meals as _meals
    date_str = date or _dt.date.today().isoformat()
    plan = _meals.eating_plan(date_str, meal if meal in _meals.MEAL_WINDOWS else 'dinner')
    plan['lines'] = _meals.plan_summary_lines(plan)
    return plan

class MealRequest(BaseModel):
    name: str
    enrich: bool = True          # let the model fill the metadata from the name

class MealPatch(BaseModel):
    # Corrections only — the editor exists so the family can fix what the
    # model guessed, not so anyone fills in twelve fields up front.
    name: Optional[str] = None
    prep_ahead_mins: Optional[int] = None
    finish_mins: Optional[int] = None
    unattended_mins: Optional[int] = None
    needs_ahead: Optional[str] = None
    holds_well: Optional[bool] = None
    portability: Optional[str] = None
    source: Optional[str] = None
    vendor: Optional[str] = None
    vendor_location: Optional[str] = None
    order_lead_mins: Optional[int] = None
    fulfillment: Optional[str] = None
    effort: Optional[str] = None
    serves: Optional[int] = None
    whole_units: Optional[bool] = None
    tags: Optional[List[str]] = None
    ingredients: Optional[List[Dict[str, Any]]] = None
    notes: Optional[str] = None
    link: Optional[str] = None
    is_active: Optional[bool] = None

@app.get("/api/meals/repertoire")
def list_meals(include_inactive: bool = False):
    return storage.get_meals(include_inactive)

@app.post("/api/meals/repertoire")
def create_meal_api(req: MealRequest):
    from services import meals as _meals
    if not (req.name or '').strip():
        raise HTTPException(status_code=400, detail="A meal needs a name")
    existing = storage.find_meal_by_name(req.name)
    if existing:
        return {**existing, 'existing': True}
    # M4: split into real dishes (falls back to the M3 single-entry path when
    # the model is unavailable, so a meal is still saved).
    if req.enrich:
        # M5: typed dishes, not a stored combination.
        return _meals.add_dishes_from_text(req.name)
    return _meals.create_meal(req.name, enrich=False)

@app.patch("/api/meals/repertoire/{meal_id}")
def patch_meal(meal_id: str, req: MealPatch):
    if not storage.get_meal(meal_id):
        raise HTTPException(status_code=404, detail="Meal not found")
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    if patch:
        storage.update_meal(meal_id, patch)
    return storage.get_meal(meal_id)

@app.delete("/api/meals/repertoire/{meal_id}")
def remove_meal(meal_id: str):
    storage.delete_meal(meal_id)
    return {"status": "ok"}

@app.post("/api/meals/repertoire/{meal_id}/served")
def meal_served(meal_id: str):
    """One tap on the surface that SUGGESTED it — rotation maintains itself
    where attention already is, or it does not get maintained."""
    meal = storage.mark_meal_served(meal_id)
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    return meal

@app.post("/api/meals/repertoire/{meal_id}/to-list")
def meal_to_list(meal_id: str, list_id: Optional[str] = None):
    from services import meals as _meals
    meal = storage.get_meal(meal_id)
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    res = _meals.ingredients_to_shopping(meal, list_id)
    _touch_stream()
    return res

class LeftoverRequest(BaseModel):
    date: Optional[str] = None
    meal_id: Optional[str] = None
    label: Optional[str] = None
    parts: List[str] = []
    dish_ids: List[str] = []
    reheat_mins: int = 10

@app.get("/api/meals/leftovers")
def list_leftovers(date: Optional[str] = None):
    import datetime as _dt
    return storage.get_leftovers(date or _dt.date.today().isoformat())

@app.post("/api/meals/leftovers")
def create_leftover(req: LeftoverRequest):
    """Mark food as already made for a day, so the plan stops holding cook
    time for it and its ingredients stay off the shopping list."""
    import datetime as _dt
    from models.schemas import Leftover
    day = req.date or _dt.date.today().isoformat()
    storage.prune_leftovers(day)
    label = req.label
    if req.meal_id and not label:
        meal = storage.get_meal(req.meal_id)
        if not meal:
            raise HTTPException(status_code=404, detail="Meal not found")
        label = meal.get('name')
    rec = Leftover(date=day, meal_id=req.meal_id, label=label,
                   parts=req.parts, dish_ids=req.dish_ids,
                   reheat_mins=req.reheat_mins).model_dump()
    storage.add_leftover(rec)
    return rec

@app.delete("/api/meals/leftovers/{leftover_id}")
def remove_leftover(leftover_id: str):
    storage.delete_leftover(leftover_id)
    return {"status": "ok"}

class DishPatch(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    role: Optional[str] = None
    prep_ahead_mins: Optional[int] = None
    finish_mins: Optional[int] = None
    unattended_mins: Optional[int] = None
    needs_ahead: Optional[str] = None
    holds_well: Optional[bool] = None
    portability: Optional[str] = None
    source: Optional[str] = None
    equipment: Optional[str] = None
    oven_temp_f: Optional[int] = None
    serves: Optional[int] = None
    scope: Optional[str] = None
    ingredients: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[str]] = None
    needs_detail: Optional[bool] = None
    is_active: Optional[bool] = None

class DishRefineRequest(BaseModel):
    description: str          # "russet, roasted" / "mashed with butter"

@app.get("/api/meals/dishes")
def list_dishes(needs_detail: bool = False):
    return storage.dishes_needing_detail() if needs_detail else storage.get_dishes()

@app.patch("/api/meals/dishes/{dish_id}")
def patch_dish(dish_id: str, req: DishPatch):
    if not storage.get_dish(dish_id):
        raise HTTPException(status_code=404, detail="Dish not found")
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    # `None` means "not sent" everywhere in this endpoint, so a temperature can
    # never be cleared by sending null — moving a dish off the oven has to do
    # it, or a stale sharing key outlives the oven that justified it.
    if patch.get('equipment') and patch['equipment'] != 'oven':
        patch['oven_temp_f'] = None
    if patch:
        storage.update_dish(dish_id, patch)
    return storage.get_dish(dish_id)

class IngredientPatch(BaseModel):
    name: str
    kind: str = 'fresh'        # staple | fresh

@app.post("/api/meals/dishes/{dish_id}/ingredient")
def set_ingredient_kind(dish_id: str, req: IngredientPatch):
    """Override the staple-vs-fresh guess for one ingredient.

    Whether beans are a pantry staple or a thing you buy is a judgement about
    THIS household — bulk buyers restock them, others assume they're in the
    cupboard — so the model's guess has to be correctable, and the skip
    reasons on the shopping drain are what make it findable.
    """
    dish = storage.get_dish(dish_id)
    if not dish:
        raise HTTPException(status_code=404, detail="Dish not found")
    kind = 'staple' if str(req.kind).lower() == 'staple' else 'fresh'
    name = (req.name or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="Which ingredient?")
    ings = [dict(i) for i in (dish.get('ingredients') or [])]
    hit = next((i for i in ings if (i.get('name') or '').strip().lower()
                == name.lower()), None)
    if hit:
        hit['kind'] = kind
    else:
        ings.append({'name': name, 'kind': kind})
    storage.update_dish(dish_id, {'ingredients': ings})
    return storage.get_dish(dish_id)

@app.post("/api/meals/dishes/{dish_id}/refine")
def refine_dish_api(dish_id: str, req: DishRefineRequest):
    """Answer the "which potatoes, and how?" question — re-derives the dish's
    times and ingredients from the sharper description."""
    from services import meals as _meals
    dish = _meals.refine_dish(dish_id, req.description)
    if not dish:
        raise HTTPException(status_code=404, detail="Dish not found")
    return dish

@app.delete("/api/meals/dishes/{dish_id}")
def remove_dish(dish_id: str):
    """Drops the dish and any slot reference to it; a slot left empty goes
    with it, so a meal never points at nothing."""
    storage.delete_dish(dish_id)
    for meal in storage.get_meals(include_inactive=True):
        slots = meal.get('slots') or []
        if not slots:
            continue
        pruned = []
        for s in slots:
            ids = [i for i in (s.get('dish_ids') or []) if i != dish_id]
            if ids:
                pruned.append({**s, 'dish_ids': ids})
        if pruned != slots:
            storage.update_meal(meal['id'], {'slots': pruned})
    return {"status": "ok"}

@app.get("/api/meals/repertoire/{meal_id}/plate")
def meal_plate(meal_id: str, date: Optional[str] = None):
    """Tonight's version of this meal: one dish per slot, with the aggregate
    timing and which parts are already made."""
    import datetime as _dt
    from services import meals as _meals
    meal = storage.get_meal(meal_id)
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    day = date or _dt.date.today().isoformat()
    return _meals.compose_meal(meal, prefer=_meals.get_choices(day, meal_id),
                               leftovers=storage.get_leftovers(day))

@app.post("/api/meals/repertoire/{meal_id}/plate")
def swap_plate_dish(meal_id: str, swap: str, after: str, date: Optional[str] = None):
    """Tap a chip to move to the next option in that slot's pool. The pick is
    a same-day preference, so it expires on its own."""
    import datetime as _dt
    from services import meals as _meals
    meal = storage.get_meal(meal_id)
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    meal = _meals.ensure_slot_ids(meal)
    day = date or _dt.date.today().isoformat()
    # Don't cycle onto a dish another slot is already showing — two "veggies"
    # slots should land on two different vegetables.
    current = _meals.compose_meal(meal, prefer=_meals.get_choices(day, meal_id),
                                  leftovers=storage.get_leftovers(day))
    siblings = {d['id'] for d in current.get('dishes') or []
                if d.get('_slot') != swap}
    nxt = _meals.next_in_pool(meal, swap, after, exclude=siblings)
    if not nxt:
        raise HTTPException(status_code=400, detail="Nothing else free in that slot")
    # Pin the WHOLE plate, then move the tapped slot. Untouched slots pick
    # automatically by avoiding what is taken, so without pinning, moving one
    # vegetable would shuffle the other one under the family's hand.
    pinned = {d['_slot']: d['id'] for d in current.get('dishes') or []}
    pinned[swap] = nxt
    _meals.set_choices(day, meal_id, pinned)
    return _meals.compose_meal(meal, prefer=_meals.get_choices(day, meal_id),
                               leftovers=storage.get_leftovers(day))

class PlateEdit(BaseModel):
    dish_id: str
    date: Optional[str] = None

@app.get("/api/meals/plate")
def tonights_plate(date: Optional[str] = None):
    """Tonight's dinner: a whole-meal dish, or one composed to the family's own
    plate shape — proposed by rule, then editable."""
    import datetime as _dt
    from services import meals as _meals
    date_str = date or _dt.date.today().isoformat()
    plan = _meals.eating_plan(date_str, 'dinner')
    # The week-aware read: the Tonight card must say what the strip's row for
    # this night says, refusals and locked-night blocks included.
    plate = _meals.showing_plate(date_str, plan)
    totals = _meals.plate_totals(plate['dishes'], date_str)
    return {'date': date_str, 'edited': plate['edited'],
            'dishes': _meals.with_chip_labels(plate['dishes']),
            'prep_ahead_mins': totals.get('prep_ahead_mins'),
            'finish_mins': totals.get('finish_mins'),
            'unattended_mins': totals.get('unattended_mins'),
            'oven_conflicts': totals.get('oven_conflicts'),
            'serving_for': totals.get('serving_for'),
            'cooks': totals.get('cooks'),
            'needs_ahead': totals.get('needs_ahead'),
            'leftover_dish_ids': totals.get('leftover_dish_ids'),
            'cook_window_mins': plan.get('cook_window_mins'),
            'split': plan.get('split'), 'packed_count': plan.get('packed_count'),
            'nobody_can_eat': plan.get('nobody_can_eat'),
            'lines': _meals.plan_summary_lines(plan)}

@app.post("/api/meals/plate/add")
def plate_add(req: PlateEdit):
    import datetime as _dt
    from services import meals as _meals
    res = _meals.add_to_plate(req.date or _dt.date.today().isoformat(), req.dish_id)
    if res.get('error'):
        raise HTTPException(status_code=404, detail=res['error'])
    return res

@app.post("/api/meals/plate/remove")
def plate_remove(req: PlateEdit):
    import datetime as _dt
    from services import meals as _meals
    return _meals.remove_from_plate(req.date or _dt.date.today().isoformat(),
                                    req.dish_id)

@app.post("/api/meals/plate/to-list")
def plate_to_list(list_id: Optional[str] = None, date: Optional[str] = None):
    """Shop for tonight's plate in ONE request: the fresh ingredients of every
    dish on it, skipping staples, already-made dishes and anything already
    open on the list."""
    import datetime as _dt
    from services import meals as _meals
    day = date or _dt.date.today().isoformat()
    plan = _meals.eating_plan(day, 'dinner')
    # Buy for the dinner being SHOWN, not an isolated re-rank of the date.
    plate = _meals.showing_plate(day, plan)
    totals = _meals.plate_totals(plate['dishes'], day)
    res = _meals.dishes_to_shopping(plate['dishes'], list_id,
                                    skip_dish_ids=totals.get('leftover_dish_ids'))
    _touch_stream()
    res['dish_count'] = len(plate['dishes'])
    return res

@app.get("/api/meals/week")
def meal_week(start: Optional[str] = None, days: Optional[int] = None):
    """The dinners ahead, composed in order.

    Both spans by default: what the last shop bought for, running out at the
    trip, and what the coming trip has to buy for. A family holds both at once
    — the second one is where an idea that lands on a Monday goes, and it is
    the only span the list can be built against. An explicit start/days still
    wins, so a card or a test can ask for one stretch of days.
    """
    from services import meals as _meals
    win = _meals.plan_window()
    if start or days:
        start_str = start or win['start']
        n = int(days) if days else win['days']
        return {'window': win, 'start': start_str, 'days': n,
                'week': _meals.compose_week(start_str, n)}
    spans = [{**s, 'week': _meals.compose_week(s['start'], s['days'])}
             for s in win['spans'] if s['days']]
    # `week` stays the span being bought for: every existing caller means that
    # by it, and the current span is a second section rather than a new default.
    buying = next((s for s in spans if s['key'] == 'next'), None)
    return {'window': win, 'spans': spans,
            'start': win['start'], 'days': win['days'],
            'week': (buying or {}).get('week', [])}

class WalmartMap(BaseModel):
    name: str
    item_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    price: Optional[float] = None
    thumbnail: Optional[str] = None

@app.get("/api/walmart/status")
def walmart_status():
    """Whether search is available. The CART never needs credentials — that
    split is the whole point, so the page can offer the cart regardless."""
    from services import walmart as _wm
    creds = _wm.get_credentials()
    return {'search_available': creds['configured'],
            'consumer_id_set': bool(creds['consumer_id']),
            'private_key_set': bool(creds['private_key']),
            'mapped_count': len(storage.get_walmart_items())}

@app.get("/api/walmart/search")
def walmart_search(q: str, limit: int = 8):
    from services import walmart as _wm
    if not _wm.is_configured():
        return {'status': 'not_configured', 'items': [],
                'message': "Walmart search isn't set up — paste a product URL instead."}
    try:
        return {'status': 'success', 'items': _wm.search(q, limit)}
    except PermissionError as pe:
        return {'status': 'error', 'items': [], 'message': str(pe)}
    except Exception as ex:
        return {'status': 'error', 'items': [],
                'message': f"Walmart search failed: {ex}"}

@app.post("/api/walmart/map")
def walmart_map(req: WalmartMap):
    """Stick a Walmart item to one of the family's words, forever."""
    from services import walmart as _wm
    item_id = (req.item_id or '').strip() or _wm.item_id_from_url(req.url or '')
    if not item_id:
        return {'status': 'error',
                'message': "I couldn't find an item id in that. Paste the "
                           "Walmart product link, or the number at the end of it."}
    rec = _wm.set_mapping(req.name, item_id, req.title, req.price, req.thumbnail)
    _touch_stream()
    return {'status': 'success', 'mapping': rec}

@app.delete("/api/walmart/map")
def walmart_unmap(name: str):
    from services import walmart as _wm
    storage.delete_walmart_item(_wm.name_key(name))
    return {'status': 'success'}

@app.get("/api/walmart/mappings")
def walmart_mappings():
    return storage.get_walmart_items()

@app.get("/api/walmart/cart")
def walmart_cart(list_id: Optional[str] = None, store_id: Optional[str] = None):
    """The cart URL for everything open on the list, plus exactly what could
    not be matched — never a silently shorter cart."""
    from services import walmart as _wm
    lid = list_id or storage.ensure_default_shopping_list()['id']
    return _wm.cart_for_list(lid, store_id)

@app.get("/api/shopping/lists/{list_id}/errand")
def shopping_list_errand(list_id: str):
    """The trip this list is bound to, and when it's actually scheduled."""
    from services import shopping as _shop
    return {'errand': _shop.errand_for_list(list_id),
            'next': _shop.next_scheduled_shop(list_id)}

@app.post("/api/shopping/lists/{list_id}/errand")
def create_shopping_list_errand(list_id: str, background_tasks: BackgroundTasks,
                                weekday: Optional[int] = None,
                                duration_mins: Optional[int] = None,
                                location: Optional[str] = None,
                                recurring: bool = True):
    """Give a list somewhere to happen — a recurring errand bound by tag, which
    the errand pass then places minimum-detour against the real week."""
    from services import shopping as _shop
    res = _shop.create_errand_for_list(list_id, weekday, duration_mins,
                                       location, recurring)
    if res.get('status') == 'success':
        background_tasks.add_task(trigger_background_refresh)
        _touch_stream()
    return res

class DishImage(BaseModel):
    url: Optional[str] = None
    source: str = 'family'

class MealRuleReq(BaseModel):
    name: str = ""
    kind: str = 'frequency_cap'         # frequency_cap | batch_cycle
    dish_ids: List[str] = []
    tags: List[str] = []
    types: List[str] = []
    side_types: List[str] = []
    sources: List[str] = []
    exclude_dish_ids: List[str] = []
    max_servings: int = 1
    window_days: int = 7
    dwell_days: int = 3

@app.get("/api/meals/rules")
def list_meal_rules():
    """How this household eats, in plain words plus what each rule matches — a
    rule matching nothing is the silent failure worth surfacing."""
    from services import meals as _meals
    dishes = storage.get_dishes()
    out = []
    for r in storage.get_meal_rules(include_disabled=True):
        matched = [d for d in dishes if _meals.rule_matches(r, d)]
        out.append({**r, 'description': _meals.describe_meal_rule(r),
                    'matches': [d.get('short_name') or d['name'] for d in matched],
                    'match_count': len(matched)})
    return {'rules': out}

@app.post("/api/meals/rules")
def create_meal_rule(req: MealRuleReq):
    from services import meals as _meals
    res = _meals.add_meal_rule(req.name, req.kind, dish_ids=req.dish_ids,
                               tags=req.tags, types=req.types,
                               side_types=req.side_types, sources=req.sources,
                               exclude_dish_ids=req.exclude_dish_ids,
                               max_servings=req.max_servings,
                               window_days=req.window_days,
                               dwell_days=req.dwell_days)
    _touch_stream()
    return res

class MealRulePatch(BaseModel):
    """Every field optional: the panel sends one for a pause and all of them
    for an edit, through the same endpoint."""
    name: Optional[str] = None
    kind: Optional[str] = None
    dish_ids: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    types: Optional[List[str]] = None
    side_types: Optional[List[str]] = None
    sources: Optional[List[str]] = None
    exclude_dish_ids: Optional[List[str]] = None
    max_servings: Optional[int] = None
    window_days: Optional[int] = None
    dwell_days: Optional[int] = None
    is_enabled: Optional[bool] = None

@app.patch("/api/meals/rules/{rule_id}")
def patch_meal_rule(rule_id: str, req: MealRulePatch):
    from services import meals as _meals
    res = _meals.edit_meal_rule(rule_id, req.model_dump(exclude_none=True))
    _touch_stream()
    return res

@app.delete("/api/meals/rules/{rule_id}")
def remove_meal_rule(rule_id: str):
    storage.delete_meal_rule(rule_id)
    _touch_stream()
    return {'status': 'success'}

class PairingReq(BaseModel):
    partner_ids: List[str] = []
    mode: str = 'always_with'      # always_with | only_with
    replace: bool = False

@app.post("/api/meals/dishes/{dish_id}/pairing")
def set_dish_pairing(dish_id: str, req: PairingReq):
    """"Brisket always comes with beans and fries" — directed, so beans and
    fries stay free to appear beside anything else."""
    from services import meals as _meals
    res = _meals.set_pairing(dish_id, req.partner_ids, req.mode, req.replace)
    _touch_stream()
    return res

@app.delete("/api/meals/dishes/{dish_id}/pairing")
def clear_dish_pairing(dish_id: str, partner_id: Optional[str] = None,
                       mode: str = 'always_with'):
    from services import meals as _meals
    res = _meals.clear_pairing(dish_id, partner_id, mode)
    _touch_stream()
    return res

class PrepStepReq(BaseModel):
    action: str
    when: str = 'hours_before'      # night_before | hours_before | morning_of
    hours: float = 1.0
    note: Optional[str] = None

@app.post("/api/meals/dishes/{dish_id}/prep")
def add_dish_prep(dish_id: str, req: PrepStepReq):
    """Work that happens outside the cook window, and the nudge for it."""
    from services import meals as _meals
    res = _meals.add_prep_step(dish_id, req.action, req.when, req.hours, req.note)
    _touch_stream()
    return res

@app.delete("/api/meals/dishes/{dish_id}/prep")
def remove_dish_prep(dish_id: str, action: Optional[str] = None,
                     step_id: Optional[str] = None):
    from services import meals as _meals
    res = _meals.remove_prep_step(dish_id, action, step_id)
    _touch_stream()
    return res

@app.get("/api/meals/prep")
def prep_ahead(days: int = 2):
    """What needs doing ahead for the nights coming up — the read behind
    "anything to do tonight?"."""
    import datetime as _dt
    from services import meals as _meals
    now = _dt.datetime.now()
    settings = storage.get_settings() or {}
    out = []
    for i in range(max(1, min(7, days))):
        date_str = (now.date() + _dt.timedelta(days=i)).isoformat()
        plan = _meals.eating_plan(date_str, 'dinner', settings=settings)
        # Week-aware: a thaw nudge for a dinner the strip is not actually
        # proposing would have somebody defrosting for a meal nobody planned.
        plate = _meals.showing_plate(date_str, plan, settings)
        for dish in plate['dishes']:
            for step in _meals.dish_prep_steps(dish):
                due = _meals.prep_step_due_at(step, date_str, settings, plan)
                out.append({'date': date_str, 'dish_id': dish['id'],
                            'dish': dish.get('short_name') or dish.get('name'),
                            'action': step['action'], 'when': step.get('when'),
                            'hours': step.get('hours'), 'note': step.get('note'),
                            'due_at': due.isoformat(),
                            'overdue': due < now})
    out.sort(key=lambda x: x['due_at'])
    return {'prep': out}

@app.get("/api/shopping/staples")
def shopping_staples(limit: int = 40):
    """What the household treats as always-on-hand — the kiosk's "we're out of
    this" grid. These never reach a list on their own, so running out of one
    had no gesture until now."""
    from services import meals as _meals
    return {'staples': _meals.household_staples(limit)}

@app.post("/api/meals/dishes/{dish_id}/image")
def set_dish_image(dish_id: str, req: DishImage):
    from services import meals as _meals
    res = _meals.set_dish_image(dish_id, req.url, req.source)
    _touch_stream()
    return res

@app.post("/api/meals/dishes/{dish_id}/image/auto")
def auto_dish_image(dish_id: str):
    """One dish, looked up now — the "try again" for a picture that came back
    wrong."""
    from services import meals as _meals
    dish = storage.get_dish(dish_id)
    if not dish:
        return {'status': 'error', 'message': 'No such dish.'}
    url = _meals.fetch_stock_image(dish)
    if not url:
        return {'status': 'error',
                'message': "No picture found. Add an Unsplash key, or take a "
                           "photo of it yourself — that one's better anyway."}
    return _meals.set_dish_image(dish_id, url, 'stock')

@app.post("/api/meals/dishes/images/backfill")
def backfill_dish_images(limit: int = 12):
    from services import meals as _meals
    return _meals.backfill_dish_images(limit)

@app.get("/api/meals/grocery-day")
def grocery_day_suggestion():
    """Which weekday actually has room for a shopping trip, and why — ranked by
    the WORST week, since a standing shop day has to work most weeks."""
    from services import meals as _meals
    settings = storage.get_settings() or {}
    return {'configured': settings.get('grocery_weekday'),
            'effective': _meals.grocery_settings(settings)[0],
            'suggestion': _meals.suggest_grocery_weekday(settings),
            'trip_mins': _meals.SHOP_TRIP_MINS}

@app.post("/api/meals/week/approve")
def meal_week_approve(start: Optional[str] = None, days: Optional[int] = None,
                      list_id: Optional[str] = None, member_id: Optional[str] = None):
    """"How does this look?" — yes. Pins every day in the window and puts the
    whole span's fresh ingredients on the list in one press."""
    from services import meals as _meals
    win = _meals.plan_window()
    res = _meals.approve_week(start or win['start'], int(days) if days else win['days'],
                              list_id, added_by=member_id)
    _touch_stream()
    res['window'] = win
    return res

@app.post("/api/meals/week/repropose")
def meal_week_repropose(start: Optional[str] = None, days: Optional[int] = None):
    """"Not this." Every unlocked night in the window is offered something
    else; locked nights are left exactly as they are."""
    from services import meals as _meals
    win = _meals.plan_window()
    start_str = start or win['start']
    n = int(days) if days else win['days']
    week = _meals.repropose_week(start_str, n)
    _touch_stream()
    return {'window': win, 'start': start_str, 'days': n,
            'week': week}

class DishCategoryReq(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    min_per_plate: int = 0
    max_per_plate: int = 1
    with_complete_meal: bool = False
    # None means "leave it as it is" — the handler rebuilds the record, and a
    # rename that silently cleared the main-dish flag would hand main-ness
    # back to sort order, the accident the flag exists to end.
    is_main: Optional[bool] = None
    order: int = 0

@app.get("/api/meals/categories")
def list_dish_categories():
    """The family's own plate vocabulary, and how much of each a plate wants."""
    cats = storage.get_dish_categories()
    dishes = storage.get_dishes()
    for c in cats:
        c['dish_count'] = len([d for d in dishes
                               if c['id'] in (d.get('category_ids') or [])])
    return {'categories': cats}

@app.post("/api/meals/categories")
def save_dish_category(req: DishCategoryReq):
    import time as _t, uuid as _uuid
    name = (req.name or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="A category needs a name")
    prior = storage.get_dish_category(req.id) if req.id else None
    lo = max(0, min(6, int(req.min_per_plate)))
    hi = max(lo, min(6, int(req.max_per_plate)))
    rec = {'id': (prior or {}).get('id') or req.id or _uuid.uuid4().hex,
           'name': name, 'description': (req.description or '').strip(),
           'min_per_plate': lo, 'max_per_plate': hi,
           'with_complete_meal': bool(req.with_complete_meal),
           'is_main': bool((prior or {}).get('is_main'))
                      if req.is_main is None else bool(req.is_main),
           'order': int(req.order),
           'created_at': (prior or {}).get('created_at') or _t.time()}
    storage.save_dish_category(rec)
    # Exactly one main: flagging this block un-flags the others in the same
    # act. (Un-flagging the current main is allowed and simply hands the
    # role to the first block via the read-side heal.)
    if rec['is_main']:
        storage.set_main_dish_category(rec['id'])
    _touch_stream()
    return rec

@app.delete("/api/meals/categories/{cat_id}")
def delete_dish_category(cat_id: str):
    touched = storage.delete_dish_category(cat_id)
    _touch_stream()
    return {'status': 'success', 'dishes_unassigned': touched}

class DishFieldsReq(BaseModel):
    """The corrections that used to need the agent: what a dish IS, and how
    many it feeds. Every one of these existed in the model and on no screen."""
    category_ids: Optional[List[str]] = None
    type: Optional[str] = None            # meal | dish
    serves: Optional[int] = None
    # v2.109.2 taught the handler below to read `whole_units` and added the
    # field to MealPatch — but not here, so every call to this endpoint hit an
    # AttributeError on a field the request could not carry and 500'd. Not just
    # the by-the-tray toggle: serves, whole-meal and the category chips all go
    # through this one handler, and the read is unconditional, so the hand path
    # for what a dish IS has been dead since. The agent's path writes the same
    # fields through a different door, which is why it kept working.
    whole_units: Optional[bool] = None
    tags: Optional[List[str]] = None

@app.patch("/api/meals/dishes/{dish_id}/fields")
def set_dish_fields(dish_id: str, req: DishFieldsReq):
    if not storage.get_dish(dish_id):
        raise HTTPException(status_code=404, detail="No such dish")
    patch = {}
    if req.category_ids is not None:
        known = {c['id'] for c in storage.get_dish_categories()}
        patch['category_ids'] = [c for c in req.category_ids if c in known]
    if req.type is not None:
        patch['type'] = 'meal' if req.type == 'meal' else 'dish'
    if req.serves is not None:
        patch['serves'] = max(1, min(50, int(req.serves)))
    if req.whole_units is not None:
        patch['whole_units'] = bool(req.whole_units)
    if req.tags is not None:
        patch['tags'] = [str(t).strip().lower()[:24] for t in req.tags[:6] if str(t).strip()]
    if patch:
        storage.update_dish(dish_id, patch)
    _touch_stream()
    return {'status': 'success', 'dish': storage.get_dish(dish_id)}

@app.get("/api/meals/history")
def meal_history(days: int = 21):
    """The nights already eaten. Plates are the record — see served_history."""
    from services import meals as _meals
    return {'history': _meals.served_history(max(1, min(120, int(days))))}

class WeekArrangeDay(BaseModel):
    date: str
    dish_ids: List[str] = []

class WeekArrangeReq(BaseModel):
    days: List[WeekArrangeDay] = []

@app.post("/api/meals/week/arrange")
def meal_week_arrange(req: WeekArrangeReq):
    """Write a whole arrangement of nights at once — the one primitive under
    both dragging a night to a new day and having last night's dinner again
    with everything else pushed back. Locked and past nights are refused,
    by name, rather than silently skipped."""
    from services import meals as _meals
    res = _meals.arrange_week([d.model_dump() for d in req.days])
    _touch_stream()
    return res

@app.post("/api/meals/plate/pin")
def plate_pin(req: PlateEdit):
    """Freeze one day as proposed, without shopping for it yet."""
    import datetime as _dt
    from services import meals as _meals
    return _meals.pin_plate(req.date or _dt.date.today().isoformat())

@app.post("/api/meals/leftovers/toggle")
def toggle_leftover(req: PlateEdit):
    """Flip one dish between already-made and not. Marking has to be
    reversible in place, or undoing it means removing the dish and re-adding
    it."""
    import datetime as _dt
    from services import meals as _meals
    day = req.date or _dt.date.today().isoformat()
    marked = _meals.toggle_leftover_dish(day, req.dish_id)
    return {"status": "ok", "dish_id": req.dish_id, "leftover": marked}

@app.post("/api/meals/plate/reset")
def plate_reset(date: Optional[str] = None, force: bool = False):
    """`force` is the per-day reset (a deliberate act on that night). The bulk
    repropose leaves it off so a locked occasion survives."""
    import datetime as _dt
    from services import meals as _meals
    return _meals.reset_plate(date or _dt.date.today().isoformat(), force)

class PlateLock(BaseModel):
    date: str
    locked: bool = True
    note: Optional[str] = None
    dish_ids: Optional[List[str]] = None

@app.post("/api/meals/plate/lock")
def plate_lock(req: PlateLock):
    """Spoken for: a night the composer must never touch."""
    from services import meals as _meals
    res = _meals.set_plate_lock(req.date, req.locked, req.note, req.dish_ids)
    _touch_stream()
    return res

class PlateHosting(BaseModel):
    date: str
    # None means "leave it alone"; 0 means "back to an ordinary night". Two
    # different statements, so they cannot share a representation.
    serving_for: Optional[int] = None
    cooks: Optional[int] = None

@app.post("/api/meals/plate/hosting")
def plate_hosting(req: PlateHosting):
    """"Twelve people on Saturday, two of us cooking." Headcount scales the
    hands-on work; hands divide it."""
    from services import meals as _meals
    res = _meals.set_plate_hosting(req.date, req.serving_for, req.cooks)
    _touch_stream()
    return res

@app.get("/api/meals/plate/runsheet")
def plate_runsheet(date: Optional[str] = None, serve: Optional[str] = None):
    """When to start, and what goes on when. Asked for, never pushed."""
    import datetime as _dt
    from services import meals as _meals
    return _meals.plate_run_sheet(date or _dt.date.today().isoformat(), serve)

# --- Occasions (arc O1) -----------------------------------------------------
# The occasion is CONTEXT, not a container: nothing lives inside it, and these
# endpoints read across the homes each thing already has.

class OccasionRequest(BaseModel):
    title: str
    anchor_date: str
    kind: str = 'gathering'
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    dish_tags: List[str] = []
    notes: Optional[str] = None
    cooks: Optional[int] = None

class OccasionPatch(BaseModel):
    title: Optional[str] = None
    kind: Optional[str] = None
    anchor_date: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    dish_tags: Optional[List[str]] = None
    notes: Optional[str] = None
    cooks: Optional[int] = None
    status: Optional[str] = None

class GuestRequest(BaseModel):
    name: str
    headcount: int = 1
    member_id: Optional[str] = None
    dietary_avoid: List[str] = []
    dietary_dislike: List[str] = []
    staying_over: bool = False
    notes: Optional[str] = None

class SourcingRequest(BaseModel):
    request: str
    list_name: Optional[str] = None
    store: Optional[str] = None
    added_by: Optional[str] = None

@app.get("/api/occasions")
def list_occasions(include_done: bool = False):
    return storage.get_occasions(include_done)

@app.post("/api/occasions")
def create_occasion(req: OccasionRequest):
    from services import occasions as _occ
    if not (req.title or '').strip():
        raise HTTPException(status_code=400, detail="An occasion needs a name")
    return _occ.create(req.title, req.anchor_date, req.kind, req.window_start,
                       req.window_end, req.dish_tags, req.notes, req.cooks)

@app.get("/api/occasions/{occasion_id}")
def get_occasion_detail(occasion_id: str):
    from services import occasions as _occ
    res = _occ.contents(occasion_id)
    if not res:
        raise HTTPException(status_code=404, detail="Occasion not found")
    return res

@app.patch("/api/occasions/{occasion_id}")
def patch_occasion(occasion_id: str, req: OccasionPatch):
    if not storage.get_occasion(occasion_id):
        raise HTTPException(status_code=404, detail="Occasion not found")
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    if patch:
        storage.update_occasion(occasion_id, patch)
    return storage.get_occasion(occasion_id)

@app.delete("/api/occasions/{occasion_id}")
def remove_occasion(occasion_id: str):
    """Deleting the context never deletes the work — the errands, lists and
    trips outlive it with their link cleared."""
    storage.delete_occasion(occasion_id)
    return {"status": "ok"}

class AttendanceRequest(BaseModel):
    member_id: str
    attending: bool

@app.get("/api/occasions/{occasion_id}/attendance")
def occasion_attendance(occasion_id: str):
    """The whole household roster with who is coming — not just the attendees.
    A list you can only add to cannot say "Grandad isn't coming this year"."""
    from services import occasions as _occ
    if not storage.get_occasion(occasion_id):
        raise HTTPException(status_code=404, detail="Occasion not found")
    return {'attendance': _occ.attendance(occasion_id),
            'headcount': _occ.headcount(occasion_id)}

@app.post("/api/occasions/{occasion_id}/attendance")
def set_occasion_attendance(occasion_id: str, req: AttendanceRequest):
    from services import occasions as _occ
    rows = _occ.set_attendance(occasion_id, req.member_id, req.attending)
    if not rows:
        raise HTTPException(status_code=404, detail="Occasion not found")
    _touch_stream()
    return {'attendance': rows, 'headcount': _occ.headcount(occasion_id)}

@app.post("/api/occasions/{occasion_id}/guests")
def add_occasion_guest(occasion_id: str, req: GuestRequest):
    from services import occasions as _occ
    if not storage.get_occasion(occasion_id):
        raise HTTPException(status_code=404, detail="Occasion not found")
    return _occ.add_guest(occasion_id, req.name, req.headcount, req.member_id,
                          req.dietary_avoid, req.dietary_dislike,
                          req.staying_over, req.notes)

@app.delete("/api/occasions/guests/{guest_id}")
def remove_occasion_guest(guest_id: str):
    storage.delete_occasion_guest(guest_id)
    return {"status": "ok"}

class AnswerRequest(BaseModel):
    key: str
    value: Any = None

@app.get("/api/occasions/{occasion_id}/interview")
def occasion_interview(occasion_id: str):
    from services import occasions as _occ
    res = _occ.interview(occasion_id)
    if not res:
        raise HTTPException(status_code=404, detail="Occasion not found")
    return res

@app.post("/api/occasions/{occasion_id}/answer")
def occasion_answer(occasion_id: str, req: AnswerRequest):
    """One answer, and whatever it cascades into. Headcount does not store a
    number — it scales every plate in the window."""
    from services import occasions as _occ
    res = _occ.answer(occasion_id, req.key, req.value)
    if res.get('error'):
        raise HTTPException(status_code=404, detail=res['error'])
    _touch_stream()
    return res

@app.post("/api/occasions/{occasion_id}/apply-template")
def occasion_apply_template(occasion_id: str, keys: Optional[List[str]] = None):
    from services import occasions as _occ
    res = _occ.apply_template(occasion_id, keys)
    if res.get('error'):
        raise HTTPException(status_code=404, detail=res['error'])
    _touch_stream()
    return res

@app.get("/api/occasions/{occasion_id}/gaps")
def occasion_gaps(occasion_id: str):
    """What is MISSING — a diff against the template and last year, never a
    list of what is already there."""
    from services import occasions as _occ
    res = _occ.gap_report(occasion_id)
    if not res:
        raise HTTPException(status_code=404, detail="Occasion not found")
    return res

class MenuRequest(BaseModel):
    dish_ids: List[str] = []
    date: Optional[str] = None

class OccasionDishRequest(BaseModel):
    description: str

@app.get("/api/occasions/{occasion_id}/menu")
def occasion_menu(occasion_id: str, date: Optional[str] = None):
    """The occasion's menu and what it costs to cook. Stores nothing of its
    own — the menu IS the locked plate on the meal date."""
    from services import occasions as _occ
    res = _occ.menu(occasion_id, date)
    if not res:
        raise HTTPException(status_code=404, detail="Occasion not found")
    return res

@app.post("/api/occasions/{occasion_id}/menu")
def set_occasion_menu(occasion_id: str, req: MenuRequest):
    from services import occasions as _occ
    res = _occ.set_menu(occasion_id, req.dish_ids, req.date)
    if res.get('error'):
        raise HTTPException(status_code=404, detail=res['error'])
    _touch_stream()
    return res

@app.delete("/api/occasions/{occasion_id}/menu")
def clear_occasion_menu(occasion_id: str, date: Optional[str] = None):
    from services import occasions as _occ
    res = _occ.clear_menu(occasion_id, date)
    if res.get('error'):
        raise HTTPException(status_code=404, detail=res['error'])
    _touch_stream()
    return res

@app.post("/api/occasions/{occasion_id}/dishes")
def add_occasion_dishes(occasion_id: str, req: OccasionDishRequest):
    """Dishes born occasion-only, so curating a holiday menu never clutters
    the list the family looks at on a Tuesday."""
    from services import occasions as _occ
    res = _occ.add_dishes(occasion_id, req.description)
    if res.get('error'):
        raise HTTPException(status_code=400, detail=res['error'])
    return res

@app.get("/api/occasions/{occasion_id}/insights")
def occasion_insights(occasion_id: str):
    """What only this app can say: who is carrying it, what is undecided and
    what that costs, the clearest day to act, deadlines that fall out of the
    food, and clashes with the real schedule."""
    from services import occasions as _occ
    if not storage.get_occasion(occasion_id):
        raise HTTPException(status_code=404, detail="Occasion not found")
    return _occ.insights(occasion_id)

@app.post("/api/occasions/{occasion_id}/dismiss/{key}")
def occasion_dismiss(occasion_id: str, key: str):
    from services import occasions as _occ
    if not _occ.dismiss(occasion_id, key):
        raise HTTPException(status_code=404, detail="Occasion not found")
    return {"status": "ok"}

@app.post("/api/occasions/{occasion_id}/source")
def source_for_occasion(occasion_id: str, req: SourcingRequest):
    """"Party favours for a shark party" → a list the occasion owns, ready for
    the cart rails that already exist."""
    from services import occasions as _occ
    res = _occ.generate_list(occasion_id, req.request, req.list_name,
                             req.store, req.added_by)
    if res.get('error'):
        raise HTTPException(status_code=400, detail=res['error'])
    _touch_stream()
    return res

@app.post("/api/meals/migrate-dishes")
def migrate_dishes():
    """One-shot: type M4's dishes and retire the slot-meals they belonged to."""
    from services import meals as _meals
    return _meals.migrate_slot_meals()

@app.get("/api/meals/suggestions")
def meal_suggestions(date: Optional[str] = None, limit: int = 5):
    """The repertoire filtered by what the day allows — a query, not planning."""
    import datetime as _dt
    from services import meals as _meals
    date_str = date or _dt.date.today().isoformat()
    plan = _meals.eating_plan(date_str, 'dinner')
    res = _meals.meals_that_fit(plan, limit=limit)
    return {'date': date_str, 'cook_window_mins': plan.get('cook_window_mins'),
            'split': plan.get('split'), 'packed_count': plan.get('packed_count'),
            'nobody_can_eat': plan.get('nobody_can_eat'),
            'leftovers': storage.get_leftovers(date_str),
            'lines': _meals.plan_summary_lines(plan), **res}

@app.post("/api/shopping/photo")
async def shopping_photo(photo: UploadFile = File(...), caption: str = Form(''),
                         list_id: str = Form('')):
    """Photo → staged shopping candidates (fridge shelf, empty packages, a
    handwritten list). Candidates are RETURNED, not added: a shelf photo
    yields a dozen guesses and the family picks. That is a picker, not an
    approval gate — adds themselves stay ungated (design principle 4)."""
    import base64
    from services import shopping as _shopping
    data = await photo.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (8MB max)")
    mime = (photo.content_type or '').lower()
    if not mime.startswith('image/'):
        raise HTTPException(status_code=400, detail="Only images are supported")
    target = list_id or storage.ensure_default_shopping_list()['id']
    res = _shopping.extract_items_from_photo(
        base64.b64encode(data).decode('ascii'), mime, (caption or '').strip())
    res['candidates'] = _shopping.already_on_list(target, res.get('candidates') or [])
    res['list_id'] = target
    return res

@app.get("/api/shopping/for-errand/{errand_id}")
def shopping_for_errand(errand_id: str):
    """The binding that makes this Chauffeur and not a list app: whoever the
    solver assigned the grocery errand gets the standing list. Matched by TAG,
    so it survives the errand regenerating on its next recurrence."""
    errand = next((e for e in storage.get_all_errands() if e.get('id') == errand_id), None)
    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")
    out = []
    for l in storage.find_shopping_lists_for_errand(errand):
        items = storage.get_shopping_items(l['id'], include_checked=False)
        out.append({**l, 'items': items, 'open_count': len(items)})
    return {"errand_id": errand_id, "errand_title": errand.get('title'), "lists": out}

# --- Kid pickup-clarity pushes (kid-support arc K2) ---

def _kid_members_for_event(ev, ev_id, sched=None):
    """Child members bound to an event as passengers — the same three-way
    binding My Day uses (calendar ids, hashtag, matched-rule passenger)."""
    from services import family_digest
    sched = sched or storage.get_cached_schedule() or {}
    matched_rules = sched.get('matched_rules', {}) or {}
    passengers = {p.get('id'): p for p in storage.get_all_passengers()}
    out = []
    for m in storage.get_all_members():
        if m.get('role') != 'child' or m.get('system') or not m.get('passenger_id'):
            continue
        p = passengers.get(m['passenger_id']) or {}
        p_cals = set(p.get('calendar_ids') or [])
        p_tags = {t.lower() for t in (p.get('hashtags') or [])}
        if family_digest._kid_event_match(ev, str(ev_id), m['passenger_id'],
                                          p_cals, p_tags, matched_rules):
            out.append(m)
    return out

def _notify_kids_ride_started(event_id, now=None):
    """K2: '🚗 Dad is on the way!' push to child passengers the moment their
    ride's first drive leg starts (PWA Start Drive button or the agent's
    start_route tool). Once per event per day (app_state marker, so later
    legs of the same drive stay quiet); kid quiet hours SKIP rather than
    defer — a stale on-the-way push is worse than none."""
    import datetime as _dt
    from services import family_digest
    try:
        now = now or _dt.datetime.now()
        if family_digest.in_kid_quiet_hours(now, storage.get_settings() or {}):
            return
        sched = storage.get_cached_schedule() or {}
        ev = next((e for e in sched.get('events', [])
                   if str(e.get('id')) == str(event_id)), None)
        if not ev:
            return
        kids = _kid_members_for_event(ev, event_id, sched)
        if not kids:
            return
        key = f"{event_id}:{now.date().isoformat()}"
        seen = dict(storage.get_app_state('ride_started_notified') or {})
        if key in seen:
            return
        cutoff = (now - _dt.timedelta(days=2)).timestamp()
        seen = {k: v for k, v in seen.items() if v >= cutoff}
        seen[key] = now.timestamp()
        storage.set_app_state('ride_started_notified', seen)
        assignments = dict(sched.get('assignments', {}))
        assignments.update(sched.get('ghost_assignments', {}))
        d_id = assignments.get(str(event_id))
        drv = storage.get_member_by_driver_id(d_id) if d_id \
            and not str(d_id).startswith('ghost_') else None
        who = (drv or {}).get('name') or 'Your driver'
        for kid in kids:
            _notify_member_lanes(kid, f"🚗 {who} is on the way!",
                                 ev.get('title') or 'Your ride', '/app')
    except Exception as e:
        print(f"Kid on-the-way push failed: {e}")

def _notify_kids_driver_changes(buffered, now=None):
    """K2: kid-worded pushes when a NEAR-TERM ride's driver changes ("Mom is
    taking you to Swim Practice today at 4:00 PM 🚗"). Rules of calm:
    GAINS only — a ride losing its driver never alarms the kid (the parent
    watchers chase unassigned events); only the next 48h — far-future churn
    is noise a kid can't act on, the evening digest covers it; kid quiet
    hours skip entirely (the digest restates tomorrow anyway)."""
    import datetime as _dt
    from services import family_digest
    now = now or _dt.datetime.now()
    if family_digest.in_kid_quiet_hours(now, storage.get_settings() or {}):
        return
    horizon = now + _dt.timedelta(hours=48)
    sched = storage.get_cached_schedule() or {}
    for ev_id, entry in buffered.items():
        old_d, new_d = entry.get("first_old"), entry.get("last_new")
        ev = entry.get("ev") or {}
        if old_d == new_d or not new_d or str(new_d).startswith("ghost_"):
            continue
        try:
            start = _dt.datetime.fromisoformat(ev["start"]).replace(tzinfo=None)
        except Exception:
            continue
        if not (now <= start <= horizon):
            continue
        drv = storage.get_member_by_driver_id(new_d)
        if not drv:
            continue
        when = "today" if start.date() == now.date() else (
            "tomorrow" if start.date() == now.date() + _dt.timedelta(days=1)
            else start.strftime('%A'))
        time_str = start.strftime('%I:%M %p').lstrip('0')
        body = (f"{drv.get('name')} is taking you to "
                f"{ev.get('title') or 'your event'} {when} at {time_str} 🚗")
        for kid in _kid_members_for_event(ev, ev_id, sched):
            _notify_member_lanes(kid, "Ride update", body, '/app')

# --- School-day-end pickup push (kid-support arc K4c) ---

def _send_school_end_push(member, now=None):
    """At dismissal, tell the kid what happens next: their first ride within
    3h after school end, with the driver named. NO ride or NO known driver ->
    send NOTHING (a 'nobody scheduled' push would alarm, and silence is what
    a no-activity afternoon looks like). Presence & Status P1 dismissal
    refresh: an active family status rides the SAME push (one push, not two)
    so the reassurance is fresh at the door, not half-forgotten from
    breakfast — and on a status day the push always goes out, ride or not
    (that day, silence is the alarm). Returns True when a push was sent."""
    import datetime as _dt
    from services import status_protocols
    now = now or _dt.datetime.now()
    try:
        day = member_day(member['id'], now.date().isoformat())
    except Exception:
        return False
    try:
        s_lines = status_protocols.kid_lines(now.date().isoformat())
    except Exception:
        s_lines = []
    s_suffix = ("\n" + "\n".join(s_lines)) if s_lines else ""
    end_s = member.get('school_hours_end') or ''
    try:
        hh, mm = [int(x) for x in end_s.split(':')[:2]]
    except (ValueError, TypeError):
        return False
    end_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    # Aftercare as a care window (load arc A5): on an aftercare day the real
    # pickup deadline is the aftercare end, not the bell — so the push tells
    # the child the truth about their afternoon FIRST, and the ride horizon
    # extends past the aftercare end rather than the school one.
    aftercare_today = (now.weekday() in (member.get('aftercare_days') or [])
                       and member.get('aftercare_until'))
    if aftercare_today:
        place = member.get('aftercare_place') or 'aftercare'
        try:
            ah, am = [int(x) for x in member['aftercare_until'].split(':')[:2]]
            ac_end = now.replace(hour=ah, minute=am, second=0, microsecond=0)
        except (ValueError, TypeError):
            ac_end = end_dt
        until = ac_end.strftime('%I:%M %p').lstrip('0')
        # Name the pickup driver when a ride sits near the aftercare end.
        who = None
        for r in day.get('rides', []):
            try:
                start = _dt.datetime.fromisoformat(r['start']).replace(tzinfo=None)
            except (ValueError, TypeError, KeyError):
                continue
            if abs((start - ac_end).total_seconds()) <= 45 * 60 and r.get('driver'):
                who = r['driver']['name']
                break
        body = (f"{(place[:1].upper() + place[1:])} until {until}"
                + (f" — {who} gets you" if who else "") + s_suffix)
        _notify_member_lanes(member, f"🏫 {(place[:1].upper() + place[1:])} today", body, '/app')
        return True
    horizon = end_dt + _dt.timedelta(hours=3)
    for r in day.get('rides', []):
        try:
            start = _dt.datetime.fromisoformat(r['start']).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue
        if not (end_dt <= start <= horizon):
            continue
        legs = r.get('legs') or []
        drv = next((l['driver'] for l in legs
                    if l.get('type') == 'dropoff' and l.get('driver')), None) \
            or r.get('driver')
        if not drv:
            continue  # unknown driver: never alarm — skip to the next ride
        t = start.strftime('%I:%M %p').lstrip('0')
        _notify_member_lanes(member, f"🚗 {drv['name']} has you after school",
                             f"{r.get('title') or 'Your ride'} at {t}{s_suffix}",
                             '/app')
        return True
    # Bus arc B1: no car ride after school — if this kid rides the bus, that
    # IS the answer (live PM stop estimate when the bus is out, else the
    # static drop time). No bus config → the original silence rule stands.
    from services import bus
    line = bus.dismissal_line(member)
    if line:
        _notify_member_lanes(member, "🚌 Bus home today", line + s_suffix, '/app')
        return True
    if s_lines:
        _notify_member_lanes(member, "💙 About today",
                             "\n".join(s_lines), '/app')
        return True
    return False

# --- Kid evening digest (kid-support arc K1) ---

def _build_kid_digests(target_date=None):
    """Per-child digest content for one day (default TOMORROW), built on
    member_day's ride resolution so the digest always matches what the kid's
    My Day shows (three-way passenger binding, split-leg collapse, per-leg
    drivers, prep items). Kids with no rides AND no routine items that day
    are omitted — nothing means nothing, never an empty ping. Returns
    {'date', 'label', 'weather', 'kids': {member_id: {name, color_code,
    avatar, lines, count, routine_count, streak}}} — shared verbatim by the
    evening Argyle DMs and the kiosk strip (GET /api/kids/digests)."""
    import datetime as _dt
    from services import family_digest, status_protocols
    target = target_date or (_dt.date.today() + _dt.timedelta(days=1))
    date_str = target.isoformat()

    # Presence & Status P1 heads-up beat: family status lines lead every
    # kid's digest, and a status day includes EVERY kid — the one day the
    # "nothing means nothing" omission must not apply is the day the kid
    # most needs to hear the message before walking through the door.
    try:
        status_lines = status_protocols.kid_lines(date_str)
    except Exception as se:
        print(f"Kid digest: status resolve failed: {se}")
        status_lines = []

    kids = {}
    for m in storage.get_all_members():
        if m.get('role') != 'child' or m.get('system'):
            continue
        try:
            day = member_day(m['id'], date_str)
        except Exception as e:
            print(f"Kid digest: day build failed for {m.get('name')}: {e}")
            continue
        lines = []
        rides = day.get('rides', [])
        # Trips lead, span-aware — a week at camp must never read like a
        # one-hour event (family feedback 2026-08-03). The away window also
        # suppresses home events the kid can't attend: nothing during camp
        # says "5:00 PM – Academy".
        away = []
        for r in rides:
            if r.get('event_type') != 'background_trip':
                continue
            lines.append(_kid_trip_line(r, target))
            # Suppression takes the span exact or not: a clipped one covers
            # fewer days than the trip, but every day it does cover is a day
            # the kid is genuinely away. Only the LINE needs exact dates.
            span = _kid_trip_span(r)
            if span['first'] is not None:
                away.append((span['first'], span['last']))
        for r in rides:
            if r.get('event_type') == 'background_trip':
                continue
            try:
                start_dt = _dt.datetime.fromisoformat(r['start']).replace(tzinfo=None)
                if any(a <= start_dt <= b for a, b in away):
                    continue  # the kid is away — this event can't happen for them
            except (ValueError, TypeError):
                pass
            try:
                t = _dt.datetime.fromisoformat(r['start']).strftime('%I:%M %p').lstrip('0')
                line = f"{t} – {r.get('title') or 'Event'}"
            except Exception:
                line = r.get('title') or 'Event'
            # Optional events: the digest must not assert a maybe. A skipped
            # occurrence says so and stops — no driver phrase, no bring-list
            # for a thing they are not attending; an undecided one is marked
            # (optional) so "5:00 PM – Open Gym" never reads as a promise.
            # An explicit 'attend' reads like any firm commitment.
            if r.get('optional') and r.get('optional_decision') == 'skip':
                lines.append(line + " — skipped today")
                continue
            if r.get('optional') and r.get('optional_decision') != 'attend':
                line += " (optional)"
            # Driver phrase: reassurance is the point. Split legs may have
            # different drivers ("Dad takes you, Mom brings you home");
            # an unassigned ride just omits the phrase — the parent watcher
            # already chases missing drivers, a kid digest must not alarm.
            legs = r.get('legs') or []
            there = next((l['driver']['name'] for l in legs
                          if l.get('type') == 'dropoff' and l.get('driver')), None)
            back = next((l['driver']['name'] for l in legs
                         if l.get('type') == 'pickup' and l.get('driver')), None)
            # Outside hands (load arc A1) leads the phrase: when a carpool
            # parent is making the run, "riding with Emma's mom" is the whole
            # answer to the question the child is actually asking, and no
            # household driver name will appear to give it.
            assist = r.get('assist')
            if assist:
                line += f" — 🚗 riding with {assist.get('label') or assist.get('name')}"
            elif there and back and there != back:
                line += f" — 🚗 {there} takes you, {back} brings you home"
            elif there or back:
                line += f" — 🚗 {there or back} is driving you"
            elif r.get('driver'):
                line += f" — 🚗 {r['driver']['name']} is driving you"
            prep = r.get('prep') or []
            if prep:
                line += f" (bring: {', '.join(prep[:4])})"
            lines.append(line)

        # K5: leave-by line first — the single most actionable fact of the
        # day. A bus launch stands on its own even with no ride lines (the
        # bus IS the ride); the car version still needs a ride to refer to.
        launch = day.get('launch')
        if launch and launch.get('bus'):
            from services import bus
            lines.insert(0, bus.digest_line(launch))
        elif launch and lines:
            who = (launch.get('driver') or {}).get('name')
            lines.insert(0, f"🚀 Leave by {launch['leave_label']}"
                            + (f" with {who}" if who else ""))

        # K4a: school tasks due within 3 days of the digest day, plus
        # overdue (gentle wording — see _task_due_label).
        task_lines = []
        for t in storage.get_kid_tasks(m['id']):
            try:
                due = _dt.date.fromisoformat(t.get('due_date') or '')
            except ValueError:
                continue
            if due <= target + _dt.timedelta(days=2):
                task_lines.append(_task_line(t, target))

        if status_lines:
            lines[:0] = status_lines  # status leads, before even the launch line

        routine_items = storage.routines_for_day(m['id'], date_str)
        if not lines and not routine_items and not task_lines:
            continue
        streak = storage.compute_streak(m['id'])
        kids[m['id']] = {
            'name': m.get('name'), 'color_code': m.get('color_code'),
            'avatar': m.get('avatar'), 'lines': lines, 'count': len(lines),
            'tasks': task_lines,
            'routine_count': len(routine_items),
            'streak': (streak or {}).get('current') or 0,
        }
    return {'date': date_str, 'label': family_digest.day_label(target),
            'weather': family_digest.weather_line(target), 'kids': kids}

def _kid_trip_span(ride):
    """(first_start, last_end) naive datetimes for the WHOLE background trip.

    The slice carries the trip's own span (`span_start`/`span_end`), and that
    is the only source that survives the solve window. Reassembling the span
    from the cached slices — which is what this used to do — can only ever see
    the part of the trip that is in view: the days before the window opened
    were never sliced at all, so the earliest surviving slice looked like day
    one. Every morning of a camp already under way, the kids were told it was
    beginning.

    Returns {'first', 'last', 'exact'}.

    `span_start`/`span_end` are the original event's own dates, copied onto
    every slice at slice time — the slicer is holding the whole trip right
    there, and the only reason this was ever hard is that it used to throw
    them away and leave the daily fragments to be reassembled afterwards.
    They cannot be: the days before the solve window opened are never sliced,
    so the earliest surviving fragment always looks like day one.

    `exact` is False only for slices cached before those fields existed. That
    resolves itself: `poll_schedule` re-runs the refresh every five minutes and
    rewrites the whole event payload, so the answer becomes exact on its own.
    An earlier cut of this tried to INFER the real span from where the
    fragments sat relative to the edges of the cache — which was a page of
    careful reasoning to bridge a five-minute gap, and reasoning is exactly
    what the dates on the slice make unnecessary. A span that is not exact is
    good enough to know the kid is away, and not good enough to say anything
    about which day it is.
    """
    import datetime as _dt

    def _naive(v):
        try:
            return _dt.datetime.fromisoformat(str(v)).replace(tzinfo=None)
        except (ValueError, TypeError):
            return None

    first, last = _naive(ride.get('span_start')), _naive(ride.get('span_end'))
    if first and last:
        return {'first': first, 'last': last, 'exact': True}

    base_id = str(ride.get('id') or '').split('_slice_')[0]
    starts, ends = [], []
    for ev in (storage.get_cached_schedule() or {}).get('events', []):
        if str(ev.get('id', '')).split('_slice_')[0] != base_id:
            continue
        s, e = _naive(ev.get('start')), _naive(ev.get('end'))
        if s and e:
            starts.append(s)
            ends.append(e)
    if not starts:
        return {'first': None, 'last': None, 'exact': False}
    return {'first': min(starts), 'last': max(ends), 'exact': False}


def _kid_trip_line(ride, target):
    """A trip deserves excitement, not a one-hour-looking time entry: turn a
    background_trip slice into a span-aware line."""
    import datetime as _dt
    title = (ride.get('title') or 'Trip').replace('✈️', '').strip()
    span = _kid_trip_span(ride)
    first, last = span['first'], span['last']
    # No dates, or dates the slicing may have clipped: name the trip and claim
    # nothing about it. Both cases are transient — a refresh is five minutes
    # away — and "day 3 of 5" read off a fragment is worse than no day at all.
    if first is None or not span['exact']:
        return f"🧳 {title}"
    # An all-day calendar event ends at midnight of the day AFTER the last day
    # it covers. Taken literally that is a trip one day too long, coming home
    # on a day nobody is travelling. (The old slice scan never had to know
    # this: each slice was already clipped to its own day.)
    last_date = last.date()
    if last_date > first.date() and last.time() == _dt.time(0, 0):
        last_date -= _dt.timedelta(days=1)
    n_days = max(1, (last_date - first.date()).days + 1)

    if target == first.date():
        line = f"🧳 {title} — {n_days}-day adventure begins! 🎉" if n_days > 1 \
            else f"🧳 {title} begins! 🎉"
        # Trip times are DESTINATION times (family convention: travel is
        # excluded — start = arrival there, end = departure from there).
        if first.hour or first.minute:
            line += f" Arriving at {first.strftime('%I:%M %p').lstrip('0')}"
        prep = ride.get('prep') or []
        if prep:
            line += f" — pack: {', '.join(prep[:4])}"
        return line
    if target == last_date:
        return f"🏠 Coming home from {title}!"
    return f"🏕️ {title} — day {(target - first.date()).days + 1} of {n_days}"


def _send_kid_digests():
    """K1 delivery: one evening Argyle DM per child previewing tomorrow.
    The DM rails push to kids with phones for free; phone-less kids see the
    SAME content on the kiosk strip (and the DM waits in their thread for
    whatever shared device they next pick up)."""
    digest = _build_kid_digests()
    weather = digest.get('weather')
    for m_id, k in (digest.get('kids') or {}).items():
        parts = [f"🌙 Tomorrow, {k['name']}!"]
        if weather:
            parts.append(weather)
        parts.extend(k['lines'] or ["No rides — free day! 🎉"])
        parts.extend(k.get('tasks') or [])
        if k['routine_count']:
            r_line = (f"📋 {k['routine_count']} routine thing"
                      f"{'s' if k['routine_count'] != 1 else ''} tomorrow")
            if k['streak']:
                r_line += f" — 🔥 {k['streak']}-day streak, keep it going!"
            parts.append(r_line)
        elif k['streak']:
            parts.append(f"🔥 {k['streak']}-day streak — keep it going!")
        try:
            from services.agent_tools_v2 import _post_chat_message
            argyle = storage.ensure_argyle_member()
            dm = storage.get_or_create_dm(argyle['id'], m_id)
            _post_chat_message(dm, argyle, "\n".join(parts))
        except Exception as e:
            print(f"Kid digest DM failed for {k.get('name')}: {e}")

def _kid_digest_default_date(now=None, settings=None):
    """The kiosk strip's day when no ?date= is given: TODAY until the
    configurable cutover (kid_digest_cutover_time, default 19:00), then
    TOMORROW — during the day the board answers today's questions; the
    evening is when a family starts planning ahead."""
    import datetime as _dt
    now = now or _dt.datetime.now()
    settings = settings if settings is not None else (storage.get_settings() or {})
    try:
        hh, mm = [int(x) for x in
                  str(settings.get('kid_digest_cutover_time', '19:00')).split(':')[:2]]
    except (ValueError, TypeError):
        hh, mm = 19, 0
    if (now.hour, now.minute) < (hh, mm):
        return now.date()
    return now.date() + _dt.timedelta(days=1)

@app.get("/api/kids/digests")
def kids_digests(date: Optional[str] = None):
    """Per-child day digest for the kiosk boards — same builder as the
    evening DMs. No ?date= -> today until the cutover time, then tomorrow;
    explicit ?date=today|tomorrow|YYYY-MM-DD always wins."""
    import datetime as _dt
    target = _kid_digest_default_date()
    if date:
        if date == 'today':
            target = _dt.date.today()
        elif date == 'tomorrow':
            target = _dt.date.today() + _dt.timedelta(days=1)
        else:
            try:
                target = _dt.date.fromisoformat(date)
            except ValueError:
                raise HTTPException(status_code=400,
                                    detail="date must be today, tomorrow, or YYYY-MM-DD")
    return _build_kid_digests(target)

# --- Status protocols & status days (Presence & Status arc P1) ---
# docs/presence_status_design.md — the "never guess" loop. Protocols are
# authored in Config -> People; days are set from My Day, the authoring UI,
# or the set_household_status agent tool. Setting/clearing announces (the
# service owns the beats); surfaces (My Day banner, kid digest/kiosk strip,
# dismissal push) read active_statuses/kid_lines.

@app.get("/api/status/protocols")
def list_status_protocols():
    return storage.get_all_status_protocols()

@app.post("/api/status/protocols")
def create_status_protocol(protocol: StatusProtocol):
    data = protocol.model_dump()
    return {"id": storage.add_status_protocol(data), "status": "success"}

@app.put("/api/status/protocols/{protocol_id}")
def update_status_protocol_endpoint(protocol_id: str, updates: dict = Body(...)):
    if not storage.get_status_protocol(protocol_id):
        raise HTTPException(status_code=404, detail="Protocol not found")
    updates.pop('id', None)
    storage.update_status_protocol(protocol_id, updates)
    return {"status": "success"}

@app.delete("/api/status/protocols/{protocol_id}")
def delete_status_protocol_endpoint(protocol_id: str):
    storage.delete_status_protocol(protocol_id)
    return {"status": "success"}

@app.get("/api/status/days")
def list_status_days(start: Optional[str] = None, end: Optional[str] = None):
    """Resolved upcoming status days (protocol joined in). Default window:
    today through +14 days — surfaces care about the near future, history
    stays queryable with explicit bounds."""
    import datetime as _dt
    from services import status_protocols
    if start is None:
        start = _dt.date.today().isoformat()
    if end is None:
        end = (_dt.date.today() + _dt.timedelta(days=14)).isoformat()
    out, seen = [], set()
    d = _dt.date.fromisoformat(start)
    end_d = _dt.date.fromisoformat(end)
    while d <= end_d:
        for s in status_protocols.active_statuses(d.isoformat()):
            if s['id'] in seen:
                continue  # a span appears once (its first covered day)
            seen.add(s['id'])
            out.append(s)
        d += _dt.timedelta(days=1)
    return out

@app.post("/api/status/days")
def create_status_day(day: StatusDay, background_tasks: BackgroundTasks):
    import datetime as _dt
    from services import status_protocols
    if not storage.get_status_protocol(day.protocol_id):
        raise HTTPException(status_code=404, detail="Protocol not found")
    try:
        _dt.date.fromisoformat(day.date)
        if day.end_date and _dt.date.fromisoformat(day.end_date) < _dt.date.fromisoformat(day.date):
            raise HTTPException(status_code=400, detail="end_date is before date")
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    day_id = storage.add_status_day(day.model_dump())
    # Announce off-request: DM fan-out can touch push endpoints and HA.
    background_tasks.add_task(status_protocols.announce_set, day_id)
    return {"id": day_id, "status": "success"}

@app.delete("/api/status/days/{day_id}")
def delete_status_day_endpoint(day_id: str, background_tasks: BackgroundTasks):
    from services import status_protocols
    row = storage.delete_status_day(day_id)
    if not row:
        raise HTTPException(status_code=404, detail="Status day not found")
    background_tasks.add_task(status_protocols.announce_cleared, row)
    return {"status": "success"}

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
def family_locations(viewer: Optional[str] = None):
    """Every member with map-relevant data: HA person state/coords (absent
    for router-based trackers -> zone chip only) plus 'driving' context from
    in-progress drive legs joined to the cached schedule's assignments.

    `viewer` is who is looking (stage arc A4): the PWA sends its selected
    member, the wall panel and /map send nothing. A Navigator's whereabouts
    go to the family, not the kiosk — with no viewer, a private-stage kid's
    zone and pin are withheld and the row says so with `private` instead.
    Driving context stays either way: "en route to practice" is the schedule
    speaking, and the kiosk already shows the schedule."""
    from services import ha_api, stages
    family_eyes = bool(viewer and storage.get_member(viewer))
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
            'image': m.get('image'),
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
        if (not family_eyes and m.get('role') == 'child'
                and stages.can(m, 'private_location')):
            # Don't read HA state only to throw it away — the kiosk gets a
            # 🔒 chip, not a zone word.
            entry['private'] = True
            out.append(entry)
            continue
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

    # Cars with a device tracker join the map (C2, docs/car_telemetry_design.md).
    # Location informs humans only — it never feeds the solver.
    try:
        from services import cars as cars_svc
        sched_ca = dict(sched.get('car_assignments', {})) if sched else {}
        driving_by_car = {}
        for leg in storage.get_in_progress_drives():
            ev_id = _leg_event_id(leg)
            c_id = sched_ca.get(ev_id)
            ev = events_by_id.get(ev_id)
            if c_id and ev and c_id not in driving_by_car:
                driving_by_car[str(c_id)] = ev.get('title') or 'a drive'
        for c in storage.get_all_cars():
            if c.get('is_disabled') or not c.get('ha_device_tracker'):
                continue
            loc = cars_svc.car_location(c) or {}
            levels = cars_svc.car_levels(c)
            out.append({
                'member_id': f"car:{c.get('id')}",
                'name': c.get('name'),
                'color_code': c.get('color_code'),
                'avatar': c.get('icon') or '🚗',
                'image': c.get('image'),
                'is_child': False,
                'is_car': True,
                'state': loc.get('state'),
                'latitude': loc.get('latitude'),
                'longitude': loc.get('longitude'),
                'gps_accuracy': loc.get('gps_accuracy'),
                'last_updated': loc.get('last_updated'),
                'battery_pct': levels.get('battery_pct'),
                'fuel_pct': levels.get('fuel_pct'),
                'range': levels.get('range'),
                'driving': {'leg_title': driving_by_car[str(c.get('id'))]} if str(c.get('id')) in driving_by_car else None,
            })
    except Exception as ce:
        print(f"family_locations: car entries failed: {ce}")
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
    # The assistant is a valid DM peer (created lazily; every message in an
    # Argyle DM routes to the agent — no @mention needed). Helpers still
    # can't: their DMs are parent-only and Argyle isn't a parent.
    if storage.ARGYLE_MEMBER_ID in (req.member_id, req.other_member_id):
        storage.ensure_argyle_member()
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

class GroupChannelRequest(BaseModel):
    member_id: str                       # creator (always included in the group)
    member_ids: List[str]                # the other participants
    title: str = ""

@app.post("/api/channels/group")
def create_group_channel(req: GroupChannelRequest):
    ids = sorted(set(req.member_ids) | {req.member_id})
    if len(ids) < 3:
        raise HTTPException(status_code=400,
                            detail="Groups need at least 3 people — use a DM instead")
    if storage.ARGYLE_MEMBER_ID in ids:
        storage.ensure_argyle_member()
    for mid in ids:
        member = storage.get_member(mid)
        if not member:
            raise HTTPException(status_code=404, detail=f"Member {mid} not found")
        # Helpers stay outside group chats entirely (same reasoning as the
        # family channel): their channel is a DM with a parent.
        if member.get('role') == 'helper':
            raise HTTPException(status_code=403,
                                detail="Helpers can't join group chats — message them directly")
    return storage.get_or_create_group(ids, req.title.strip())

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
    body: str = ''
    # Photo moment (Presence slice): {kind:'photo', data_url, w?, h?}. The
    # PWA downscales client-side (~1280px JPEG); the server just bounds it.
    attachment: Optional[dict] = None

# Photos are persisted as FILES (like clips), so the wire cap only has to be
# generous enough for the PWA's ~2048px q0.85 rendition — not tight enough to
# protect the database, which is what the old 1 MB limit was really doing.
_ATTACHMENT_MAX_CHARS = 16_000_000

def _validate_moment_attachment(att: dict) -> dict:
    """Normalize/validate a moment attachment; raises HTTPException on junk.
    Photos are inline data URLs; videos reference an uploaded media file
    (/api/moments/upload -> /api/media/{id})."""
    if not isinstance(att, dict):
        raise HTTPException(status_code=400, detail="Unsupported attachment")
    if att.get('kind') == 'photo':
        # Already-stored photo (re-post / migration passthrough).
        url = str(att.get('url') or '')
        if url.startswith('/api/media/') and storage.media_file_path(url.rsplit('/', 1)[-1]):
            out = {'kind': 'photo', 'url': url}
        else:
            data_url = str(att.get('data_url') or '')
            if not data_url.startswith('data:image/'):
                raise HTTPException(status_code=400, detail="Attachment must be an image data URL")
            if len(data_url) > _ATTACHMENT_MAX_CHARS:
                raise HTTPException(status_code=413, detail="Photo too large — try again")
            # Persist to the media store rather than inline on the message:
            # the database stays small and the photo streams like a clip.
            saved = storage.save_photo_data_url(data_url)
            if not saved:
                raise HTTPException(status_code=400, detail="Unsupported image format")
            out = {'kind': 'photo', 'url': saved['url'], 'mime': saved['mime']}
        for k in ('w', 'h'):
            if isinstance(att.get(k), (int, float)):
                out[k] = int(att[k])
        return out
    if att.get('kind') == 'video':
        url = str(att.get('url') or '')
        media_id = url.rsplit('/', 1)[-1] if url.startswith('/api/media/') else ''
        if not media_id or not storage.media_file_path(media_id):
            raise HTTPException(status_code=400, detail="Video upload not found — try again")
        return {'kind': 'video', 'url': f'/api/media/{media_id}',
                'mime': storage.media_mime(media_id)}
    raise HTTPException(status_code=400, detail="Unsupported attachment kind")

import re as _re
# Matches an @argyle mention anywhere in a message (case-insensitive).
_ARGYLE_MENTION = _re.compile(r'@argyle\b', _re.IGNORECASE)


def _mentions_argyle(body: str) -> bool:
    return bool(body) and bool(_ARGYLE_MENTION.search(body))


def _run_argyle_mention(channel: dict, sender: dict, body: str):
    """Background worker: a chat message @mentioned Argyle (or landed in an
    Argyle DM, where every message is implicitly for the assistant). Route the
    question to the agent as the sending member (known identity + role scope)
    and post the reply back into the same channel as the Argyle system member.
    Runs off-request because an agent turn can take tens of seconds."""
    from services.agent_router import process_agent_request
    from services.agent_tools_v2 import _post_chat_message
    query = _ARGYLE_MENTION.sub('', body).strip()
    if not query:
        query = ("The user mentioned you in the family chat without asking anything. "
                 "Greet them briefly by name and ask how you can help.")
    card = None
    try:
        res = process_agent_request(query, source="family", acting_member=sender)
        reply = (res or {}).get("message") or "Sorry — I couldn't work that out."
        card = res.get("card")
        if res.get("schedule_dirty"):
            trigger_background_refresh()
    except Exception as e:
        logger.error(f"Argyle mention handling failed: {e}")
        reply = "Sorry — I hit an error handling that."
    # Bind any proposed action to this channel so its Approve/Dismiss follow-up
    # posts back here.
    if card and card.get("proposal_id"):
        storage.update_action_proposal(card["proposal_id"], {"channel_id": channel["id"]})
    try:
        argyle = storage.ensure_argyle_member()
        _post_chat_message(channel, argyle, reply, card=card)
        # K3 (kid-as-sensor): a child's proposal card created in a private DM
        # is invisible to the people who can approve it — mirror the card into
        # the family channel (normal fan-out notifies the parents) and re-bind
        # the proposal there, so the Approve tap's outcome follow-up lands
        # where the parents actually saw the card.
        if card and card.get("proposal_id") and channel.get('kind') == 'dm' \
                and (sender or {}).get('role') == 'child':
            try:
                storage.ensure_family_channel()
                fam = storage.get_family_channel()
                storage.update_action_proposal(card["proposal_id"],
                                               {"channel_id": fam["id"]})
                _post_chat_message(fam, argyle,
                                   f"💡 {sender.get('name') or 'One of the kids'} "
                                   f"flagged this for a parent:", card=card)
            except Exception as me:
                logger.error(f"Kid proposal mirror failed: {me}")
    except Exception as e:
        logger.error(f"Argyle reply post failed: {e}")


@app.post("/api/channels/{channel_id}/messages")
def send_message(channel_id: str, req: SendMessageRequest, background_tasks: BackgroundTasks):
    channel = storage.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if channel.get('archived'):
        raise HTTPException(status_code=409, detail="Channel is archived")
    body = (req.body or '').strip()
    attachment = _validate_moment_attachment(req.attachment) if req.attachment else None
    if not body and not attachment:
        raise HTTPException(status_code=400, detail="Empty message")
    sender = storage.get_member(req.sender_member_id)
    if not sender:
        raise HTTPException(status_code=404, detail="Sender member not found")
    if channel.get('kind') in ('dm', 'group') \
            and req.sender_member_id not in (channel.get('member_ids') or []):
        raise HTTPException(status_code=403, detail="Not a member of this chat")
    if sender.get('role') == 'helper' and channel.get('kind') != 'dm':
        raise HTTPException(status_code=403, detail="Helpers can only post in their DMs")

    from models.schemas import ChatMessage
    message = ChatMessage(channel_id=channel_id,
                          sender_member_id=req.sender_member_id,
                          body=body, attachment=attachment).model_dump()
    storage.add_chat_message(message)
    # Sender has obviously read their own message.
    storage.set_last_read(channel_id, req.sender_member_id, message['ts'])
    recipients = channel.get('member_ids') if channel.get('kind') in ('dm', 'group') else None
    # A moment carries its own preview on the stream so an open app can pop it
    # (the kiosk hearth experience for whoever is holding a phone).
    meta = None
    if attachment and channel.get('kind') == 'event':
        try:
            from services import presence
            meta = presence.moment_stream_meta(channel, message, sender)
        except Exception as me:
            print(f"Moment stream meta failed: {me}")
    _push_message_event(channel_id, recipients, meta)
    background_tasks.add_task(_fanout_message_notifications, channel, message)
    # @argyle turns the family chat into a vector of action: hand the message to
    # the agent as the sender and let it reply in-channel. In an Argyle DM the
    # whole thread IS the conversation with the agent, so every message routes
    # without a mention. Never re-trigger on Argyle's own posts.
    is_argyle_dm = channel.get('kind') == 'dm' \
        and storage.ARGYLE_MEMBER_ID in (channel.get('member_ids') or [])
    if req.sender_member_id != storage.ARGYLE_MEMBER_ID \
            and (is_argyle_dm or _mentions_argyle(body)):
        background_tasks.add_task(_run_argyle_mention, channel, sender, body)
    elif req.sender_member_id != storage.ARGYLE_MEMBER_ID:
        # Implicit detection (opt-in): Tier 1 keyword pre-filter gates the
        # expensive funnel so ordinary chatter never reaches the agent.
        from services import chat_actions
        if storage.get_settings().get('chat_suggestions_enabled') and chat_actions.suggests_action(body):
            background_tasks.add_task(chat_actions.run_suggestion_funnel, channel, sender, body)
    return message

class ChannelReadRequest(BaseModel):
    member_id: str
    ts: Optional[float] = None

@app.post("/api/channels/{channel_id}/read")
def mark_channel_read(channel_id: str, req: ChannelReadRequest):
    storage.set_last_read(channel_id, req.member_id, req.ts or time.time())
    return {"status": "ok"}

class ReactRequest(BaseModel):
    member_id: str
    emoji: str

@app.post("/api/messages/{message_id}/react")
def react_to_message(message_id: str, req: ReactRequest):
    """Toggle a reaction. Deliberately NEVER pushes — the parent at the game
    is fire-and-forget; reactions accumulate silently and show at a break
    (Presence design). Open threads refresh via the SSE ring only."""
    emoji = (req.emoji or '').strip()
    if not emoji or len(emoji) > 8:
        raise HTTPException(status_code=400, detail="Invalid reaction")
    if not storage.get_member(req.member_id):
        raise HTTPException(status_code=404, detail="Member not found")
    msg = storage.toggle_message_reaction(message_id, req.member_id, emoji)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    channel = storage.get_channel(msg['channel_id']) or {}
    recipients = channel.get('member_ids') if channel.get('kind') in ('dm', 'group') else None
    _push_message_event(msg['channel_id'], recipients)
    return msg

class MessageEditRequest(BaseModel):
    member_id: str
    body: str

class MessageDeleteRequest(BaseModel):
    member_id: str

def _may_delete_message(msg: dict, member: dict, channel: dict) -> bool:
    """Your own message, always. A PARENT may also clear anything out of a
    SHARED space (event/group) — that is the "kid posted the wrong clip to
    the team chat" case, and role='parent' is the existing admin role (not
    every adult: a grandparent or a sitter is an adult, not an authority).
    DMs stay sender-only so nobody reaches into a private thread."""
    if msg.get('sender_member_id') == member.get('id'):
        return True
    return member.get('role') == 'parent' and channel.get('kind') in ('event', 'group')

@app.delete("/api/messages/{message_id}")
def delete_message(message_id: str, req: MessageDeleteRequest):
    """Delete a message and any media it owns. No tombstone — this exists so a
    misfired photo can be UNDONE, and "X deleted a photo" just advertises the
    thing you were trying to take back. Best-effort by nature: a push already
    on a lock screen cannot be recalled, and a kiosk mid-overlay keeps the
    bytes it already loaded. Everything else self-heals (open threads over
    SSE, the hearth rail on its 60 s poll)."""
    member = storage.get_member(req.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    msg = storage.get_chat_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    channel = storage.get_channel(msg['channel_id']) or {}
    if not _may_delete_message(msg, member, channel):
        raise HTTPException(status_code=403, detail="Not yours to delete")
    storage.delete_chat_message(message_id)
    recipients = channel.get('member_ids') if channel.get('kind') in ('dm', 'group') else None
    _push_message_event(msg['channel_id'], recipients)
    return {"status": "ok", "id": message_id, "channel_id": msg['channel_id']}

@app.patch("/api/messages/{message_id}")
def edit_message(message_id: str, req: MessageEditRequest):
    """Edit your own message's text. SENDER ONLY, deliberately narrower than
    delete: a parent removing something from a shared channel is moderation,
    but a parent rewriting a kid's words puts words in their mouth. Captions
    on moments are editable the same way; the media itself never changes."""
    body = (req.body or '').strip()
    member = storage.get_member(req.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    msg = storage.get_chat_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.get('sender_member_id') != req.member_id:
        raise HTTPException(status_code=403, detail="You can only edit your own messages")
    # An empty body is only legal when an attachment still carries the message
    # — otherwise editing to blank is a delete wearing a disguise.
    if not body and not msg.get('attachment'):
        raise HTTPException(status_code=400, detail="Message cannot be empty — delete it instead")
    updated = storage.edit_chat_message(message_id, body)
    channel = storage.get_channel(msg['channel_id']) or {}
    recipients = channel.get('member_ids') if channel.get('kind') in ('dm', 'group') else None
    _push_message_event(msg['channel_id'], recipients)
    return updated

@app.get("/api/presence/moments")
def get_presence_moments(hours: float = 12, limit: int = 12):
    """Recent moments (photos + clips) from event chats — the hearth feed.
    Time-windowed on purpose; the gallery uses the paged endpoints below."""
    from services import presence
    return presence.recent_moments(hours=min(hours, 720), limit=min(limit, 200))

@app.get("/api/presence/moment-events")
def get_moment_events(offset: int = 0, limit: int = 24):
    """Gallery top level: one card per event with moments, newest first."""
    from services import presence
    return presence.moment_events(offset=max(0, offset), limit=min(max(1, limit), 60))

@app.get("/api/presence/event-moments")
def get_event_moments(channel_id: str, offset: int = 0, limit: int = 30):
    """Every moment for one event, newest first, paged."""
    from services import presence
    return presence.event_moments(channel_id, offset=max(0, offset),
                                  limit=min(max(1, limit), 100))

@app.get("/api/debug/media")
def debug_moment_media():
    """Is the moment media pipeline healthy on THIS box? Chiefly: did the
    add-on image actually bring ffmpeg (posters + transcoding depend on it,
    and a Dockerfile change only lands on a REBUILD, not a restart)."""
    ffmpeg = storage._ffmpeg_path()
    files = []
    # Walk, not listdir: media is sharded into ab/cd buckets, and files may
    # still be sitting in the legacy root mid-migration. Counted PER ROOT and
    # split flat-vs-sharded, because "is my media actually on the share yet"
    # is the whole question after pointing media_root somewhere new — and a
    # migration that moved nothing logs nothing, so the log cannot answer it.
    by_root = {}
    for root in storage._media_roots():
        flat = sharded = 0
        try:
            for dirpath, _dirnames, names in os.walk(root):
                keep = [n for n in names if not n.startswith('.')]
                files.extend(keep)
                if os.path.normpath(dirpath) == os.path.normpath(root):
                    flat += len(keep)
                else:
                    sharded += len(keep)
        except OSError as e:
            by_root[root] = {'error': str(e)}
            continue
        by_root[root] = {'total': flat + sharded, 'flat': flat, 'sharded': sharded}
    clips = [f for f in files if os.path.splitext(f)[1] in ('.mp4', '.webm', '.mov', '.m4v')]
    posters = {os.path.splitext(f)[0] for f in files if f.endswith('.jpg')}
    missing = [c for c in clips if os.path.splitext(c)[0] not in posters]
    inline = 0
    with storage.db_lock:
        for m in storage.chat_messages_table.all():
            att = m.get('attachment') or {}
            if att.get('kind') == 'photo' and att.get('data_url'):
                inline += 1
    return {
        'ffmpeg': ffmpeg or None,
        'ffmpeg_ok': bool(ffmpeg),
        'media_dir': storage.MEDIA_DIR,
        # Loud when a configured media_root was REFUSED (missing mount, no
        # write permission) and the archive quietly stayed on /data.
        'media_root_configured': storage._configured_media_root() or None,
        'media_root_active': storage.MEDIA_DIR != storage._LEGACY_MEDIA_DIR,
        'legacy_media_dir': storage._LEGACY_MEDIA_DIR,
        # Where the bytes ACTUALLY are. Anything left under the legacy root
        # has not been relocated yet; 'flat' under the active root means it
        # has not been sharded yet. POST /api/debug/media/migrate to re-run.
        'files_by_root': by_root,
        # False means media_dir is a plain folder on the add-on's own volume,
        # not a mounted share — the usual cause is a media_root whose spelling
        # does not match the mount name in HA.
        'media_root_is_mount': storage._is_separate_filesystem(storage.MEDIA_DIR),
        # Uploads and transcodes work on the ADD-ON's volume even when media
        # is stored elsewhere — this is the number that matters if HA starts
        # misbehaving during an upload.
        'scratch_dir': storage.media_scratch_dir(),
        'scratch_free_gb': round(storage.scratch_free_bytes() / (1024 ** 3), 2),
        'scratch_reserve_gb': round(_DISK_RESERVE_BYTES / (1024 ** 3), 2),
        'scratch_in_use_bytes': sum(
            os.path.getsize(os.path.join(storage.media_scratch_dir(), n))
            for n in (os.listdir(storage.media_scratch_dir())
                      if os.path.isdir(storage.media_scratch_dir()) else [])
            if os.path.isfile(os.path.join(storage.media_scratch_dir(), n))),
        'clips': len(clips),
        'posters': len(posters),
        'clips_missing_posters': missing[:20],
        'photos_still_inline': inline,
        'hint': ('OK' if ffmpeg else
                 'ffmpeg missing — REBUILD the add-on (a restart will not pick up '
                 'the Dockerfile change). Clip thumbnails fall back to video tiles '
                 'until then.'),
    }

class MediaAdoptRequest(BaseModel):
    path: str

@app.post("/api/debug/media/adopt")
async def debug_media_adopt(req: MediaAdoptRequest):
    """Recover media from a directory the app no longer knows about — the
    case where media_root changed before that history was being recorded (a
    renamed share strands the whole back catalogue while new uploads work).
    Registers the path permanently, so its files resolve immediately, then
    relocates them into the active root."""
    path = (req.path or '').strip().rstrip('/')
    if not path or not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")
    added = storage.adopt_media_root(path)
    res = await asyncio.to_thread(storage.migrate_media_layout)
    res.update({'adopted': path, 'newly_added': added,
                'roots': storage._media_roots()})
    return res

@app.post("/api/debug/media/migrate")
async def debug_media_migrate():
    """Re-run the media layout relocation now, without an add-on restart.
    Safe to call repeatedly: on a settled archive it is a directory walk with
    no moves, and files are served from wherever they are throughout."""
    res = await asyncio.to_thread(storage.migrate_media_layout)
    res['media_dir'] = storage.MEDIA_DIR
    res['media_root_is_mount'] = storage._is_separate_filesystem(storage.MEDIA_DIR)
    return res

@app.get("/api/moments/{message_id}/media")
def serve_moment_media_by_message(message_id: str):
    """Stable per-moment media URL. Photos are stored as inline data URLs
    (great in a thread, ruinous in a 200-thumbnail gallery payload), so they
    are decoded to real image bytes here; clips defer to the media store.
    This is what lets the gallery page lazily and cache."""
    import base64
    msg = storage.get_chat_message(message_id) or {}
    att = msg.get('attachment') or {}
    if str(att.get('url', '')).startswith('/api/media/'):
        return RedirectResponse(att['url'])
    data_url = str(att.get('data_url') or '')
    if att.get('kind') == 'photo' and data_url.startswith('data:image/'):
        try:
            head, _, b64 = data_url.partition(',')
            mime = head.split(':', 1)[1].split(';', 1)[0]
            return Response(base64.b64decode(b64), media_type=mime,
                            headers={'Cache-Control': 'private, max-age=86400'})
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="Moment media not found")

# "Photos of sports does nothing. Videos are the thing." (family, 2026-08-04)
# Clips upload as files on the family's box and transcode to H.264 720p in
# the background (Dockerfile ships ffmpeg), so the raw upload cap can be
# generous — the STORED clip ends up ~20x smaller. Raised from 500 MB once
# media_root could point at real storage and uploads became resumable: the
# cap existed to bound a single-shot upload onto the add-on's own volume,
# and both halves of that are gone. A phone's own 4K60 clip is the unit here.
_VIDEO_MAX_BYTES = 2 * 1024 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 5 * 1024 * 1024
# Abandoned parts are swept far more aggressively than they were: at 2 GB a
# handful of failed retries can fill /data long before a 24 h sweep runs.
_UPLOAD_STALE_SECS = 2 * 3600
# Never let uploads take the volume below this. Home Assistant shares it.
_DISK_RESERVE_BYTES = 4 * 1024 * 1024 * 1024


def _upload_paths(upload_id: str):
    """Part file + its sidecar. The id regex is the traversal guard."""
    import re
    if not re.fullmatch(r'[a-f0-9]{32}', upload_id or ''):
        raise HTTPException(status_code=400, detail="Bad upload id")
    d = storage.media_scratch_dir()
    return os.path.join(d, upload_id + '.part'), os.path.join(d, upload_id + '.meta')


def _sweep_stale_uploads():
    """Abandoned resumable uploads are real bytes on disk — a dropped 2 GB
    clip nobody retried would otherwise sit in scratch forever."""
    d = storage.media_scratch_dir()
    cutoff = time.time() - _UPLOAD_STALE_SECS
    try:
        for name in os.listdir(d):
            if not name.endswith(('.part', '.meta')):
                continue
            p = os.path.join(d, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


class UploadInitRequest(BaseModel):
    size: int
    mime: str = ''


@app.post("/api/moments/upload/init")
def init_resumable_upload(req: UploadInitRequest):
    """Reserve a resumable upload. Validates the size BEFORE a single byte
    moves — the client already knows `file.size`, so a clip that is too big
    should cost nothing but one round trip, not a full transfer that fails at
    the end. (On iOS the slow part before this is the OS pulling the video out
    of iCloud; nothing server-side can shorten that.)"""
    import uuid as _uuid
    if req.size <= 0:
        raise HTTPException(status_code=400, detail="Empty upload")
    if req.size > _VIDEO_MAX_BYTES:
        gb = _VIDEO_MAX_BYTES / (1024 ** 3)
        raise HTTPException(
            status_code=413,
            detail=f"That clip is {req.size / (1024**3):.1f}GB — the limit is {gb:.0f}GB")
    _sweep_stale_uploads()
    # The real limit is not the cap, it is the add-on's own volume. Uploads
    # and transcodes work in /data, which Home Assistant shares — running it
    # out does not merely fail this upload, it takes HA down with it. Refuse
    # early and say so, keeping a hard reserve free no matter what.
    free = storage.scratch_free_bytes()
    need = int(req.size * 1.15) + _DISK_RESERVE_BYTES
    if free and free < need:
        raise HTTPException(
            status_code=507,
            detail=(f"Not enough working space on the add-on's disk for a "
                    f"{req.size / (1024**3):.1f}GB clip "
                    f"({free / (1024**3):.1f}GB free). Uploads need room on /data "
                    f"to transcode even when media is stored elsewhere."))
    upload_id = _uuid.uuid4().hex
    part, meta = _upload_paths(upload_id)
    with open(part, 'wb'):
        pass
    with open(meta, 'w') as f:
        json.dump({'size': req.size, 'mime': req.mime or '', 'created': time.time()}, f)
    return {'upload_id': upload_id, 'received': 0,
            'chunk_size': _UPLOAD_CHUNK_BYTES, 'max_bytes': _VIDEO_MAX_BYTES}


@app.get("/api/moments/upload/{upload_id}")
def resumable_upload_status(upload_id: str):
    """How many bytes the server actually has — the client resyncs to this
    after a dropped connection instead of starting over."""
    part, meta = _upload_paths(upload_id)
    if not os.path.isfile(part) or not os.path.isfile(meta):
        raise HTTPException(status_code=404, detail="Upload not found")
    with open(meta) as f:
        info = json.load(f)
    return {'upload_id': upload_id, 'received': os.path.getsize(part),
            'size': info.get('size')}


@app.put("/api/moments/upload/{upload_id}")
async def put_upload_chunk(upload_id: str, offset: int, request: Request):
    """Append one chunk at `offset`. A mismatched offset is a 409 carrying the
    true `received`, so a client that lost track resyncs in one round trip
    rather than restarting the transfer."""
    part, meta = _upload_paths(upload_id)
    if not os.path.isfile(part) or not os.path.isfile(meta):
        raise HTTPException(status_code=404, detail="Upload not found")
    with open(meta) as f:
        info = json.load(f)
    have = os.path.getsize(part)
    if offset != have:
        raise HTTPException(status_code=409,
                            detail=json.dumps({'received': have}))
    # Buffer the chunk, then write it OFF the event loop. A synchronous
    # f.write() inside an async handler blocks EVERY other request for its
    # duration — with a few uploads in flight that serializes them against
    # each other and stalls the SSE stream and thread refreshes besides.
    # One chunk (5 MB) per in-flight request is the memory cost.
    limit = min(info['size'], _VIDEO_MAX_BYTES)
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if have + len(buf) > limit:
            for p in (part, meta):
                try:
                    os.remove(p)
                except OSError:
                    pass
            raise HTTPException(status_code=413,
                                detail="Upload exceeded its declared size")
    if buf:
        def _append(data=bytes(buf)):
            with open(part, 'ab') as f:
                f.write(data)
        await asyncio.to_thread(_append)
        have += len(buf)
    return {'received': have, 'size': info['size']}


@app.post("/api/moments/upload/{upload_id}/complete")
def complete_resumable_upload(upload_id: str):
    """Finalize: hand the assembled file to the media store exactly as the
    one-shot path does (transcode kicks off in the background from there)."""
    part, meta = _upload_paths(upload_id)
    if not os.path.isfile(part) or not os.path.isfile(meta):
        raise HTTPException(status_code=404, detail="Upload not found")
    with open(meta) as f:
        info = json.load(f)
    have = os.path.getsize(part)
    if have != info['size']:
        raise HTTPException(
            status_code=400,
            detail=f"Incomplete upload — have {have} of {info['size']} bytes")
    os.remove(meta)
    saved = storage.finalize_media_upload(part, info.get('mime') or '')
    if not saved:
        raise HTTPException(status_code=400, detail="Unsupported video format")
    _sweep_stale_uploads()   # a finished upload is a good moment to tidy
    return {'kind': 'video', 'url': saved['url'], 'mime': saved['mime']}

@app.post("/api/moments/upload")
async def upload_moment_media(media: UploadFile = File(...)):
    import uuid as _uuid
    # Stream to LOCAL scratch, not the media root: a several-hundred-MB
    # upload should not hold a network mount open for the whole transfer.
    # finalize_media_upload moves the finished file across.
    part = os.path.join(storage.media_scratch_dir(), _uuid.uuid4().hex + '.part')
    size = 0
    # Stream to disk — a phone clip must never sit in RAM whole.
    with open(part, 'wb') as f:
        while True:
            chunk = await media.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > _VIDEO_MAX_BYTES:
                f.close()
                os.remove(part)
                raise HTTPException(status_code=413,
                                    detail="Clip too large (500MB max) — try a shorter one")
            f.write(chunk)
    if not size:
        os.remove(part)
        raise HTTPException(status_code=400, detail="Empty upload")
    saved = storage.finalize_media_upload(part, media.content_type or '')
    if not saved:
        raise HTTPException(status_code=400, detail="Unsupported video format")
    return {'kind': 'video', 'url': saved['url'], 'mime': saved['mime']}

@app.get("/api/media/{media_id}")
def serve_media_file(media_id: str, request: Request):
    """Range-aware media serving — iOS Safari refuses to play video without
    byte-range support, and Starlette's FileResponse can't be relied on for
    it across versions, so the 206 path is explicit."""
    path = storage.media_file_path(media_id)
    if not path:
        raise HTTPException(status_code=404, detail="Media not found")
    size = os.path.getsize(path)
    mime = storage.media_mime(media_id)
    range_header = request.headers.get('range', '')
    if range_header.startswith('bytes='):
        try:
            start_s, _, end_s = range_header[6:].partition('-')
            start = int(start_s) if start_s else 0
            end = min(int(end_s), size - 1) if end_s else size - 1
        except ValueError:
            raise HTTPException(status_code=416, detail="Bad range")
        if start > end or start >= size:
            raise HTTPException(status_code=416, detail="Bad range")
        def _chunked(p, s, e, chunk=1024 * 512):
            with open(p, 'rb') as f:
                f.seek(s)
                remaining = e - s + 1
                while remaining > 0:
                    block = f.read(min(chunk, remaining))
                    if not block:
                        break
                    remaining -= len(block)
                    yield block
        return StreamingResponse(
            _chunked(path, start, end), status_code=206, media_type=mime,
            headers={'Content-Range': f'bytes {start}-{end}/{size}',
                     'Accept-Ranges': 'bytes',
                     'Content-Length': str(end - start + 1),
                     'Cache-Control': 'private, max-age=86400'})
    return FileResponse(path, media_type=mime,
                        headers={'Accept-Ranges': 'bytes',
                                 'Cache-Control': 'private, max-age=86400'})

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
                        payload = {'channel_id': ev['channel_id']}
                        if ev.get('moment'):
                            payload['moment'] = ev['moment']
                        yield f"data: {_json.dumps(payload)}\n\n"
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
            
    # M1: the standing shopping lists bound to each errand by tag, so the
    # errand card shows what the trip is actually FOR. Computed once here
    # rather than one request per card.
    all_lists = storage.get_shopping_lists()
    open_counts = {}
    for l in all_lists:
        open_counts[l['id']] = len(storage.get_shopping_items(l['id'], include_checked=False))

    res = []
    for e in raw:
        obj = Errand(**e).model_dump() if hasattr(Errand(**e), 'model_dump') else Errand(**e).dict()
        if obj['id'] in errand_schedules:
            obj['scheduled_start'] = errand_schedules[obj['id']]
        obj['shopping_lists'] = [
            {'id': l['id'], 'name': l['name'], 'open_count': open_counts.get(l['id'], 0)}
            for l in storage.find_shopping_lists_for_errand(obj)]
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
        # Heavy tier: override-pattern analysis is rare and quality-critical.
        from services import model_pools
        llm_model = model_pools.resolve_model('heavy', settings) if llm_provider == 'gemini' else settings.get('llm_ollama_model', 'qwen2.5:7b')
        
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

@app.post("/api/events/{event_id}/optional_decision")
def set_optional_decision_api(event_id: str, body: dict = Body(default={})):
    """Optional events, phase 2: the per-occurrence attend/skip choice.
    Resolves the cached-schedule event so the decision is keyed by the
    occurrence's own google id — recurring siblings are never touched."""
    from services import optional_events
    sched = storage.get_cached_schedule() or {}
    ev = next((e for e in sched.get('events', [])
               if str(e.get('id')) == str(event_id)), None)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found in the current schedule.")
    if not ((ev.get('app_config') or {}).get('is_optional')):
        raise HTTPException(status_code=400, detail="That event is not marked optional.")
    res = optional_events.record_decision(ev, body.get('decision'),
                                          decided_by=body.get('member_id'))
    if res.get('status') != 'success':
        raise HTTPException(status_code=400, detail=res.get('message'))
    # The decision rides the events hash, so this re-solve does real work.
    trigger_background_refresh()
    return res

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

@app.get("/api/settings/index")
def settings_index(q: Optional[str] = None):
    """Every setting, grouped, with where it lives.

    Decentralising settings onto the surfaces that own them destroys exactly
    one thing a big config page was good at: somewhere to look when you
    half-remember a setting but not which page owns it. This is that place.
    """
    from services import settings_registry as _reg
    current = storage.get_settings() or {}
    return {'groups': _reg.search(q, current) if q else _reg.index(current),
            'query': q or ''}

@app.post("/api/settings")
def update_settings(settings: Settings, background_tasks: BackgroundTasks):
    # MERGE, don't replace: clients send only the fields they manage (the
    # config page doesn't know about intake creds; /intake doesn't know about
    # solver toggles). exclude_unset keeps model defaults from clobbering
    # stored values a client never sent — a blind replace here silently wiped
    # intake mailbox credentials on every config-page save.
    incoming = settings.model_dump(exclude_unset=True)
    current = storage.get_settings() or {}
    # A home address must never keep a stale/poisoned geocode: purge its
    # cache entries when the address changes, or when the stored entry
    # isn't street-level ('city'/'failed') — so re-saving settings is a
    # user-visible "force a fresh lookup" lever.
    new_home = (incoming.get('home_location') or '').strip()
    if new_home:
        changed = new_home != (current.get('home_location') or '').strip()
        row = storage.get_cached_geocode(new_home) \
            or storage.get_cached_geocode(maps.extract_street_address(new_home))
        suspect = bool(row) and (row.get('precision') or 'exact') != 'exact'
        if changed or suspect:
            for key in {new_home, maps.extract_street_address(new_home)}:
                if key:
                    storage.delete_cached_geocode(key)
    # Flipping the toll policy changes what every cached minute MEANS: the
    # static cache is deliberately immortal, so it has to burn here or the
    # app keeps quoting the other policy's durations indefinitely.
    if 'routing_avoid_tolls' in incoming and \
            bool(incoming.get('routing_avoid_tolls')) != bool(current.get('routing_avoid_tolls')):
        storage.clear_route_caches()
    current.update(incoming)
    storage.update_settings(current)
    # Panel-shaped settings (layout, theme, screensaver…) edited on one device
    # must repaint every wall panel — they reload on the `profile` stream
    # event. Everything else rides the generic `update` bump.
    global LAST_UPDATE_TIME, LAST_PROFILE_TIME
    if any(k.startswith('panel_') for k in incoming):
        LAST_PROFILE_TIME = time.time()
    LAST_UPDATE_TIME = time.time()
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
        # Heavy tier: philosophy -> rules is a rare, quality-critical generation.
        from services import model_pools
        model = model_pools.resolve_model('heavy', settings)
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
        # Interactive tier: the user is waiting on the refine button.
        from services import model_pools
        model = model_pools.resolve_model('interactive', settings)
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

# --- Travel-time forensics ---
@app.get("/api/debug/travel")
def debug_travel(destination: Optional[str] = None, event: Optional[str] = None,
                 origin: Optional[str] = None, fresh: bool = False):
    """Answers "why does the app think X is N minutes away?" end to end:
    what each address CLEANED to, what it GEOCODED to (display name +
    precision — a wrong venue match is visible here), the straight-line km,
    the cached Matrix duration the solver uses, and (?fresh=true, costs two
    Directions calls) fresh free-flow vs TRAFFIC-AWARE durations — which
    separates 'geocoded the wrong place' from 'free-flow profile vs rush
    hour'. ?event=<title substring> resolves the destination from the
    cached schedule so nobody has to copy addresses around."""
    from services import maps as _maps
    from services.cars import _haversine_m
    settings = storage.get_settings() or {}
    origin = (origin or settings.get('home_location') or '').strip()
    matched_title = None
    drive_status = None
    if event and not destination:
        low = event.lower()
        sched = storage.get_cached_schedule() or {}
        matches = [e for e in sched.get('events', [])
                   if low in (e.get('title') or '').lower()]
        ev = matches[0] if matches else None
        if not ev:
            raise HTTPException(status_code=404,
                                detail=f"No cached event title contains '{event}'")
        destination = (ev.get('location') or '').strip()
        matched_title = ev.get('title')
        # Say what KIND of thing was matched, out loud. A title-substring hit
        # on the wrong sibling ("Girls" vs "Girls 2033") sent a whole debug
        # session to the wrong venue — and an event nobody is assigned to
        # drive has NO leave time, so its numbers are informational, not a
        # departure anyone is being told about.
        eid = ev.get('id')
        assigned = (sched.get('assignments') or {}).get(eid) \
            or (sched.get('assignments') or {}).get(f"{eid}_dropoff")
        drive_status = {
            "matched_event_id": eid,
            "assigned_driver": assigned,
            "is_scheduled_drive": bool(assigned),
            "note": None if assigned else
                    "NOT a scheduled drive (no driver assigned — likely no "
                    "passengers configured). No leave-by, push, or day-of "
                    "traffic exists for it; the numbers below are "
                    "informational only.",
        }
        if len(matches) > 1:
            drive_status["also_matched"] = [
                {"title": m.get('title'), "start": m.get('start'),
                 "location": m.get('location')} for m in matches[1:4]]
        if not destination:
            return {"event": matched_title, "drive_status": drive_status,
                    "problem": "This event has NO location — travel times for it "
                               "are guesses, not routes."}
    if not destination:
        raise HTTPException(status_code=400, detail="Pass ?destination= or ?event=")

    def side(addr):
        cleaned = _maps.extract_street_address(addr)
        coords = _maps.geocode_address(addr)
        row = storage.get_cached_geocode(cleaned) or storage.get_cached_geocode(addr) or {}
        return {"raw": addr, "cleaned": cleaned, "coords": coords,
                "resolved_to": row.get('display_name'),
                "precision": row.get('precision') or ('legacy' if row else None)}

    o, d = side(origin), side(destination)
    out = {"event": matched_title, "origin": o, "destination": d}
    if drive_status:
        out["drive_status"] = drive_status
    if o["coords"] and d["coords"]:
        out["straight_line_km"] = round(_haversine_m(
            o["coords"][0], o["coords"][1], d["coords"][0], d["coords"][1]) / 1000, 1)
    out["cached_matrix_mins"] = storage.get_cached_travel_time(
        origin.lower(), destination.lower(), ignore_age=True)
    # The day-of layer (v2.165.0): what the sweep has bought for this pair
    # TODAY — the number the hero, the PWA and the pushes are acting on.
    # Read through maps: the cache is coordinate-keyed (v2.165.1), so any
    # spelling of the same two places finds the row.
    out["day_of_traffic"] = _maps.get_day_of_traffic(origin, destination)
    # Which origin each DRIVER actually routes from: a driver record's own
    # home_location OVERRIDES the global home (solver initial edges,
    # matcher.py) — the classic source of a "9 minutes" chip while the
    # global-home pair above says 25. uses_own_address: true + a different
    # resolved_to is the smoking gun.
    drivers_out = []
    for drv in storage.get_all_drivers():
        if drv.get('is_disabled'):
            continue
        own = (drv.get('home_location') or '').strip()
        eff = own or origin
        drivers_out.append({
            "driver": drv.get('name'),
            "uses_own_address": bool(own),
            "origin": side(eff) if own else "(global home — origin block above)",
            "cached_matrix_mins_to_destination": storage.get_cached_travel_time(
                eff.lower(), destination.lower(), ignore_age=True),
        })
    out["drivers"] = drivers_out
    if fresh:
        for label, profile in (("fresh_freeflow_mins", "driving"),
                               ("fresh_traffic_mins", "driving-traffic")):
            try:
                geo = _maps.get_route_geometry(origin, destination, profile=profile)
                out[label] = round(float(geo.get('duration_mins')), 1) if geo else None
            except Exception as e:
                out[label] = f"error: {e}"
    out["how_to_read"] = (
        "resolved_to wrong place -> geocode problem (re-save the address or fix the "
        "event location). resolved_to right + big gap between cached_matrix_mins and "
        "fresh_traffic_mins -> the free-flow profile vs real traffic: the app "
        "deliberately buys static no-traffic durations (see system_capabilities.md "
        "Travel Time), so rush-hour drives read optimistic.")
    return out

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


def _apply_identity_colors(cal_meta: dict) -> dict:
    """Family-member identity color (color_code) is the single source of truth
    for person colors. Calendar metadata colors were only ever a deterministic
    hash of the calendar id string (calendar.get_calendar_metadata) — nobody
    chose them. Overlays the member's color onto every metadata entry they
    own: their passenger-id key and all linked driver/passenger calendar ids.
    Must run at SERVE time (not just cache-build time) so a color edit shows
    up without waiting for caches to rebuild."""
    if not cal_meta:
        return cal_meta
    try:
        drivers_by_id = {d.get('id'): d for d in storage.get_all_drivers()}
        pax_by_id = {p.get('id'): p for p in storage.get_all_passengers()}
        for m in storage.get_all_members():
            color = m.get('color_code')
            if not color:
                continue
            # The person's own calendars and (for a calendar-only person) the
            # member id their events are attributed to, plus the legacy mirror
            # keys — one color, every surface.
            keys = [str(m.get('id'))]
            keys.extend(m.get('calendar_ids') or [])
            d = drivers_by_id.get(m.get('driver_id'))
            if d:
                keys.extend(d.get('calendar_ids') or [])
            p = pax_by_id.get(m.get('passenger_id'))
            if p:
                keys.append(str(p.get('id')))
                keys.extend(p.get('calendar_ids') or [])
            for k in keys:
                if k in cal_meta and isinstance(cal_meta[k], dict):
                    cal_meta[k] = {**cal_meta[k], 'backgroundColor': color}
    except Exception as ex:
        logger.warning(f"Identity color overlay failed: {ex}")
    return cal_meta


def _calendar_legend_members() -> list:
    """The people the calendar legend is built from — everyone, including the
    ones with no driving or passenger profile, who exist on no other list.

    Read live rather than out of a schedule cache: like the identity-color
    overlay, a rename, a recolor or a newly added person must show without
    waiting for a cache rebuild."""
    return [{
        "id": m['id'],
        "name": m.get('name') or '',
        "color_code": m.get('color_code') or '#3B82F6',
        "avatar": m.get('avatar'),
        "driver_id": m.get('driver_id'),
        "passenger_id": m.get('passenger_id'),
        "calendar_ids": m.get('calendar_ids') or [],
    } for m in storage.get_all_members()]


def _identity_driver_colors(driver_list) -> list:
    """Serve drivers with their member identity color so dashboard columns
    match event bars and pills; the driver record's own color_code is a
    legacy field kept only as a fallback."""
    out = []
    for d in driver_list or []:
        dd = d.dict() if hasattr(d, 'dict') else dict(d)
        m = storage.get_member_by_driver_id(dd.get('id'))
        if m and m.get('color_code'):
            dd['color_code'] = m['color_code']
        out.append(dd)
    return out


@app.post("/api/calendars/metadata")
def get_calendars_metadata(calendar_ids: list[str]):
    return _apply_identity_colors(calendar.get_calendar_metadata(calendar_ids))

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

def hash_events(events_list, assist_map=None):
    sorted_events = sorted(events_list, key=lambda e: getattr(e, 'id', ''))
    parts = []
    for e in sorted_events:
        eid = getattr(e, 'id', '')
        parts.append(f"{eid}|{getattr(e, 'start', '')}|{getattr(e, 'end', '')}|{getattr(e, 'location', '')}|{getattr(e, 'title', '')}")
        # Outside-hands coverage rides the hash (load arc A1). Handing a drive
        # to a carpool parent changes nothing about the EVENT, so without this
        # the day's cache stays valid and the solver keeps a household driver
        # on a ride somebody else is making — the change would appear to do
        # nothing until the next forced refresh.
        # Resolved the same way the solver resolves it (instance, then series),
        # or a series hand-over would leave every daily cache valid and appear
        # to do nothing until the next forced refresh.
        if assist_map:
            _cov = _assist_svc.coverage_for(assist_map, e)
            if _cov:
                parts.append(f"assist:{eid}:{_cov}")
        # Optionality and its per-occurrence decision ride the hash for the
        # same reason: ticking Optional or answering attend/skip changes
        # nothing about the EVENT, only about how it should be solved.
        conf = getattr(e, 'app_config', None) or {}
        dec = getattr(e, 'optional_decision', None)
        if conf.get('is_optional') or dec:
            parts.append(f"opt:{eid}:{1 if conf.get('is_optional') else 0}:{dec or ''}")
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

def is_display_only_event(e) -> bool:
    """An event the family must SEE but the solver must never touch.

    All-day events are the whole category today. You cannot be driven to a
    thing with no time of day, so they carry no scheduling meaning — but they
    carry a great deal of FAMILY meaning: a no-school day, a birthday, "Dad in
    Chicago". Those were dropped at fetch and therefore appeared on no screen
    at all, which made the calendar a view of the driving schedule rather than
    a view of the family's life.

    The reason they must stay out of the solver is specific and severe: a
    midnight-to-midnight span overlaps every drive that day, and matcher 3c
    ("Driver Personal Calendar Overlaps") BANS a driver from any event that
    truly overlaps one of their personal events. One birthday on a parent's
    calendar would take them off every drive that day.

    A background trip is the exception: an all-day trip IS scheduling
    information, and the solver has always been meant to see it.
    """
    return (bool(getattr(e, 'all_day', False))
            and getattr(e, 'event_type', '') != 'background_trip')


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

    cars_data = storage.get_all_cars()
    cars = [Car(**{k: v for k, v in c.items() if k != 'doc_id'}) for c in cars_data if not c.get('is_disabled', False)]

    passenger_calendar_map = {}
    passenger_calendar_ids = set()
    for p in passengers:
        passenger_calendar_map[str(p.id)] = p
        for cid in p.calendar_ids:
            if cid and cid.strip():
                c = cid.strip()
                passenger_calendar_ids.add(c)
                passenger_calendar_map[c] = p
                
    # Calendars belong to the PERSON (FamilyMember.calendar_ids); the driver and
    # passenger lists above are mirrors of it. A member with neither link — a
    # person who drives themselves and chauffeurs nobody — has no mirror to be
    # read from, so their calendars are collected here directly. Their events
    # are shown and count as busy, but never become ride demand: see
    # `is_member_only` in the event loop below.
    members_data = storage.get_all_members()
    member_calendar_map = {}
    member_only_calendar_ids = set()
    for m in members_data:
        if m.get('driver_id') or m.get('passenger_id'):
            continue
        for cid in (m.get('calendar_ids') or []):
            if cid and cid.strip():
                c = cid.strip()
                member_only_calendar_ids.add(c)
                member_calendar_map[c] = m

    all_cals_to_fetch = sorted(list(set(calendar_ids) | driver_calendar_ids
                                    | passenger_calendar_ids | member_only_calendar_ids))

    # If there are no calendars to fetch at all, return an error
    if not all_cals_to_fetch:
        return {"error": "No calendar IDs configured in settings or on any person."}
    
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
                    
            # All-day events used to be dropped right here, which is why a
            # no-school day existed on no Chauffeur screen. They now flow on
            # and are held back one step later — after the UI payload, before
            # the solver. See is_display_only_event().
            all_fetched_events.append(e)
            
        pass

    except Exception as e:
        return {"error": f"Failed to fetch events: {str(e)}"}
        
    # Removed global hash check. We now do day-by-day hashing and caching below.
    events = []
    all_events_for_ui = {} # To avoid duplicates in payload
    # Events owned by a person with no driving/passenger profile: display-only,
    # kept out of the solver, the inbox and duplicate detection.
    member_only_event_ids = set()

    driver_events_map = {d.id: [] for d in drivers}
    driver_events_ids = {d.id: [] for d in drivers}

    rules_data = storage.get_all_rules()
    priority_rules_data = storage.get_all_priority_rules()
    overrides_data = [] if ignore_overrides else storage.get_all_overrides()
    # Outside hands (load arc A1): {key: contact_id} for work somebody outside
    # this household is covering, keyed by instance id or series google id.
    # Read once for the whole refresh; the per-day slice is resolved inside the
    # solve loop. Spent instance rows are retired to the history table first —
    # the refresh is the sweep that already runs often enough, and yesterday's
    # carpool cannot change any solve from here on.
    # Local alias: this function imports `datetime` further down, which makes
    # the bare name local to the WHOLE body — the same reason `_sd_dt` exists.
    import datetime as _assist_dt
    storage.archive_past_assist_assignments(_assist_dt.date.today().isoformat())
    assist_map = storage.get_assist_assignment_map()

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

    # Presence & Status P2: status days whose need is 'cover'/'help' take the
    # affected member's driver out of the rotation for that date, as synthetic
    # one-day 'unavailable' rules — the existing matcher machinery (bans +
    # "marked unavailable" diagnostics) does the rest. Immune to the
    # standard/AI rule toggles: a chemo day isn't a routing preference.
    # Status-day mutations invalidate the schedule caches (storage), so these
    # always reflect the current days.
    try:
        import datetime as _sd_dt
        from services import status_protocols as _status
        _sd_start = _sd_dt.date.today().isoformat()
        # The full build horizon (load arc A5 fix). This was hardcoded to 14
        # days against a 30-day `days_to_build`, so a cover day 20 days out
        # was announced to the whole family while the solver went right on
        # scheduling that parent for it.
        _sd_days = int(settings.get('days_to_build', 30) or 30)
        _sd_end = (_sd_dt.date.today() + _sd_dt.timedelta(days=_sd_days)).isoformat()
        for entry in _status.unavailable_driver_dates(_sd_start, _sd_end):
            rules.append(Rule(driver_id=entry['driver_id'],
                              constraint_type='unavailable',
                              start_date=entry['date'],
                              end_date=entry.get('end_date') or entry['date'],
                              # clear_deck/give_space teeth (A6): evening-only.
                              time_start=entry.get('time_start'),
                              time_end=entry.get('time_end')))
            logger.info(f"Status day: {entry['label']} -> driver {entry['driver_id']} "
                        f"unavailable {entry['date']}..{entry.get('end_date') or entry['date']}")
    except Exception as _se:
        logger.warning(f"Status-day unavailability injection failed: {_se}")

    # Protected commitments (load arc A6): a standing piece of somebody's own
    # life — the run club, therapy, choir — as recurring unavailable windows.
    # The one place an adult's time is FOR something rather than an obstacle.
    try:
        from services import stages as _stg  # noqa: F401  (import guard parity)
        for pc in storage.get_protected_commitments():
            member = storage.get_member(pc.get('member_id')) or {}
            drv = member.get('driver_id')
            if not drv or not pc.get('days_of_week'):
                continue
            rules.append(Rule(driver_id=drv, constraint_type='unavailable',
                              days_of_week=list(pc['days_of_week']),
                              time_start=pc.get('time_start'),
                              time_end=pc.get('time_end')))
            logger.info(f"Protected: {pc.get('title')} -> driver {drv} "
                        f"unavailable {pc.get('days_of_week')} "
                        f"{pc.get('time_start')}-{pc.get('time_end')}")
    except Exception as _pce:
        logger.warning(f"Protected-commitment injection failed: {_pce}")

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

        # The line between "the family's calendar" and "the driving schedule".
        # Everything above this point is what the family SEES; everything below
        # it is what the solver reasons about. A display-only event stops here:
        # it is in the UI payload, and it never reaches the solve set, the
        # inbox, or driver_events — where a 24-hour span would ban its owner
        # from every drive that day. See is_display_only_event().
        if is_display_only_event(e):
            continue

        # 2. Check Passengers (Config -> Rules -> Calendar/Hashtags)
        matched_passengers = []
        is_passenger = False

        driver_calendar_ids = [c for d in drivers for c in d.calendar_ids]
        is_driver_only = (
            all(c in driver_calendar_ids for c in original_calendar_ids) and
            len(original_calendar_ids) > 0 and
            not any(c in calendar_ids for c in original_calendar_ids)
        )
        # An event off a calendar-only person's calendar: theirs to attend, and
        # nobody's to drive. It renders on the family calendar under their name
        # and color, but never reaches the solver and never nags the inbox.
        is_member_only = (
            len(original_calendar_ids) > 0 and
            all(c in member_only_calendar_ids for c in original_calendar_ids) and
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
                    # Rules store passenger ids OR raw calendar ids (calendar-created
                    # rules use the latter) — resolve both, exactly like
                    # does_event_match_rule does, so the event's calendar_ids get
                    # rewritten to real passenger ids. Leaving raw calendar ids
                    # here blinded the trip-away suppression filter downstream.
                    matched_pax = [p for p in passengers
                                   if str(p.id) in rule.passenger_ids
                                   or (p.calendar_ids and any(c in rule.passenger_ids for c in p.calendar_ids))]
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
        elif is_member_only:
            # Attribute to the person, exactly as passenger events are attributed
            # to a passenger id — that is what makes their name and color show on
            # the event and their legend chip filter it.
            owners = []
            for c in original_calendar_ids:
                owner = member_calendar_map.get(c)
                if owner and str(owner['id']) not in owners:
                    owners.append(str(owner['id']))
            if owners:
                e.calendar_ids = owners
                member_only_event_ids.add(e.id)

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
        # Driver-only and person-only events bypass the inbox to avoid clutter —
        # neither is a ride waiting to be assigned.
        if not config and not is_driver_only and not is_member_only:
            e.needs_triage = True

        # 5. Append to events list if it's a passenger event AND has a location
        # (needs_triage events still go to the dashboard but are stripped out of solver below)
        if is_passenger and not is_member_only:
            events.append(e)

    # Optional events, phase 2: stamp each optional event with the family's
    # per-occurrence decision (attend/skip/undecided) before unrolling, so
    # every unrolled copy carries it. Skips leave the solve per-day below;
    # attends regain full weight in the solver.
    from services import optional_events as _opt
    _opt.stamp_decisions(events)

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
                # A cid may be a resolved passenger id OR a raw Google calendar
                # id (events bound by a rule with no resolvable passengers keep
                # their raw cids). Resolve to passenger entities the same way
                # the solver's compute_event_trip_entities does, so both sides
                # agree on who is on the trip.
                cid_entities = {f"passenger_{p.id}" for p in passengers
                                if str(cid) == str(p.id) or (p.calendar_ids and cid in p.calendar_ids)}
                if not cid_entities:
                    cid_entities = {f"passenger_{cid}"}
                on_trip = False
                for tm in trip_metadata:
                    if cid_entities.issubset(tm['entities']) or 'global' in tm['entities']:
                        trip_start = tm['start']
                        trip_end = tm['end']
                        # Keep passengers on events NEAR the trip destination — an
                        # on-trip driver can still take them there. Only meaningful
                        # when the trip actually HAS a driver ('global' counts): a
                        # kid away at camp alone has no one to shuttle them, so the
                        # solver bans every driver regardless of distance. The
                        # radius MUST match the solver's on-trip driver limit
                        # (60 min, see matcher.py trip-assignment constraint):
                        # any passenger kept here but unassignable by every driver
                        # surfaces as a bogus red "Needs driver".
                        is_near_trip = False
                        trip_has_driver = 'global' in tm['entities'] or any(
                            str(ent).startswith('driver_') for ent in tm['entities'])
                        if trip_has_driver and tm.get('location') and getattr(e, 'location', None):
                            try:
                                tt = maps.get_travel_time_minutes(e.location, tm['location'])
                                # The 15-minute routing fallback counts as near.
                                if tt <= 60:
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

    # A kid double-booked between their solo event and a co-attended event
    # knocks the co-attended event fully off the schedule (constraint 2b makes
    # the pair mutually exclusive). Drop the kid from the co-attended event so
    # it can still schedule for the remaining kids.
    conflict_drops = matcher.resolve_passenger_double_bookings(events, passengers)
    for _ev_id, _pids in conflict_drops.items():
        logger.info(f"Double-booking resolved: dropped passenger(s) {_pids} from {_ev_id}")

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
                    # What the WHOLE trip is, before this loop throws it away.
                    # Only the days inside the solve window get a slice, so the
                    # slices cannot be reassembled into the trip afterwards —
                    # the first days of a camp already under way simply do not
                    # exist as events, and reading "day one" off the earliest
                    # surviving slice is how it kept telling the kids their
                    # trip was beginning.
                    daily_e.span_start = e.start.astimezone()
                    daily_e.span_end = e.end.astimezone()
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
        combined_car_assignments = {}
        combined_assist_assignments = {}
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
                combined_car_assignments.update(sched.get('car_assignments', {}))
                combined_assist_assignments.update(sched.get('assist_assignments', {}))
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

            # Same treatment for calendar-only people, keyed by member id — the
            # id their events were attributed to above.
            for m in members_data:
                if m.get('driver_id') or m.get('passenger_id'):
                    continue
                calendar_metadata[str(m['id'])] = {
                    "summary": m.get('name') or 'Family member',
                    "backgroundColor": m.get('color_code') or '#3B82F6',
                    "foregroundColor": "#ffffff"
                }

        if draft and not force_refresh:
            diagnostics = {}
        else:
            diagnostics = matcher.compute_diagnostics(
                combined_true_unassigned, list(all_events_for_ui.values()), drivers, driver_events_map, combined_assignments, overrides, rules, passengers=passengers, trip_metadata=trip_metadata, cars=cars
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
            # ...and person-only ones: a recurring work block is not a duplicate
            # ride to be collapsed.
            if e.id in member_only_event_ids:
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
            "car_assignments": combined_car_assignments,
            "cars": cars,
            # Outside hands (load arc A1): {event_id: contact_id}, plus the
            # contacts themselves so every surface can name and ring them
            # without a second request.
            "assist_assignments": combined_assist_assignments,
            # decorate(): carries `helps_with` so the drives page can offer
            # only the people who drive, without a second synonym table in JS.
            "assist_contacts": _assist_svc.decorate(
                storage.get_assist_contacts(include_inactive=True)),
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
            "calendar_metadata": _apply_identity_colors(calendar_metadata),
            "lateness_warnings": combined_lateness_warnings,
            "passenger_calendar_ids": calendar_ids,
            "driver_events": driver_events_ids,
            "home_location": home_location or "",
            "diagnostics": diagnostics,
            "matched_rules": matched_rules,
            "passengers": passengers,
            # The people themselves — the calendar legend is built from this, so
            # someone with no driving/passenger profile still gets a chip.
            "members": _calendar_legend_members(),
            "drivers": _identity_driver_colors(drivers),
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
                    
                    # origin/travel_static_mins: the leg the push is FOR, so
                    # the day-of traffic sweep can re-price it and move the
                    # fire time up when the road is slow (maps.py). Pushes
                    # anchored to an event's END carry no route on purpose —
                    # traffic does not change when a game finishes.
                    def add_init_notif(nid, ts, body, loc, origin=None, static=None):
                        if now_ts <= ts + 600:
                            pending_notifications.append({
                                "notif_id": nid, "driver_id": d_id, "trigger_timestamp": ts,
                                "title": "Time to Leave!", "body": body, "location": loc, "fired": nid in fired_notif_ids,
                                "origin": origin or None, "destination": loc if origin else None,
                                "travel_static_mins": static or None
                            })

                    if pickup_wp:
                        pax_pickup_loc = pickup_wp.get("pickup_location", "")
                        driver_home_loc = edge.get("driver_home_location", "")
                        if pax_pickup_loc == driver_home_loc:
                            dep_time = ev_start_ts - (pickup_wp.get("from_global_home_mins", 0) + 5 + buffer_before) * 60
                            add_init_notif(f"init_{ev_id}", dep_time, f"Drive to {ev.location.split(',')[0]}", ev.location,
                                           origin=driver_home_loc, static=pickup_wp.get("from_global_home_mins", 0))
                        else:
                            dep1 = ev_start_ts - (pickup_wp.get("from_driver_home_mins", 0) + pickup_wp.get("from_global_home_mins", 0) + 5 + buffer_before) * 60
                            add_init_notif(f"init_{ev_id}_1", dep1, f"Pickup at {pax_pickup_loc.split(',')[0]}", pax_pickup_loc,
                                           origin=driver_home_loc, static=pickup_wp.get("from_driver_home_mins", 0))
                            dep2 = ev_start_ts - (pickup_wp.get("from_global_home_mins", 0) + 5 + buffer_before) * 60
                            add_init_notif(f"init_{ev_id}_2", dep2, f"Drive to {ev.location.split(',')[0]}", ev.location,
                                           origin=pax_pickup_loc, static=pickup_wp.get("from_global_home_mins", 0))
                    else:
                        dep_time = ev_start_ts - (edge.get("travel_mins", 0) + 5 + buffer_before) * 60
                        add_init_notif(f"init_{ev_id}", dep_time, f"Drive to {ev.location.split(',')[0]}", ev.location,
                                       origin=edge.get("driver_home_location") or settings.get("home_location"),
                                       static=edge.get("travel_mins", 0))
                        
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
                    
                    def add_notif(nid, ts, body, loc, origin=None, static=None):
                        if now_ts <= ts + 600:
                            pending_notifications.append({
                                "notif_id": nid, "driver_id": d_id, "trigger_timestamp": ts,
                                "title": "Time to Leave!", "body": body, "location": loc, "fired": nid in fired_notif_ids,
                                "origin": origin or None, "destination": loc if origin else None,
                                "travel_static_mins": static or None
                            })

                    if home_wp and pickup_wp:
                        pax_pickup_loc = pickup_wp.get("pickup_location", "")
                        driver_home_loc = home_wp.get("driver_home_location", "")
                        dep1 = ev_end_ts + buffer_after * 60
                        add_notif(f"route_{ev_id}_{next_ev.id}_1", dep1, "Drive Home", settings.get("home_location", ""))
                        if pax_pickup_loc == driver_home_loc:
                            dep2 = max(dep1, next_ev_start_ts - (pickup_wp.get("from_pickup_mins", 0) + buffer_before + 5) * 60)
                            add_notif(f"route_{ev_id}_{next_ev.id}_2", dep2, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location,
                                      origin=pax_pickup_loc, static=pickup_wp.get("from_pickup_mins", 0))
                        else:
                            dep2 = max(dep1, next_ev_start_ts - (home_wp.get("from_home_mins", 0) + pickup_wp.get("from_pickup_mins", 0) + buffer_before + 5) * 60)
                            add_notif(f"route_{ev_id}_{next_ev.id}_2", dep2, f"Pickup at {pax_pickup_loc.split(',')[0]}", pax_pickup_loc,
                                      origin=driver_home_loc, static=home_wp.get("from_home_mins", 0))
                            dep3 = max(dep2, next_ev_start_ts - (pickup_wp.get("from_pickup_mins", 0) + buffer_before + 5) * 60)
                            add_notif(f"route_{ev_id}_{next_ev.id}_3", dep3, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location,
                                      origin=pax_pickup_loc, static=pickup_wp.get("from_pickup_mins", 0))
                    elif home_wp:
                        dep1 = ev_end_ts + buffer_after * 60
                        add_notif(f"route_{ev_id}_{next_ev.id}_1", dep1, "Drive Home", settings.get("home_location", ""))
                        dep2 = max(dep1, next_ev_start_ts - (home_wp.get("from_home_mins", 0) + buffer_before + 5) * 60)
                        add_notif(f"route_{ev_id}_{next_ev.id}_2", dep2, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location,
                                  origin=home_wp.get("driver_home_location") or settings.get("home_location"),
                                  static=home_wp.get("from_home_mins", 0))
                    elif pickup_wp:
                        dep1 = ev_end_ts + buffer_after * 60
                        add_notif(f"route_{ev_id}_{next_ev.id}_1", dep1, f"Pickup at {pickup_wp.get('pickup_location', 'Location').split(',')[0]}", pickup_wp.get("pickup_location", ""))
                        dep2 = max(dep1, next_ev_start_ts - (pickup_wp.get("from_pickup_mins", 0) + buffer_before + 5) * 60)
                        add_notif(f"route_{ev_id}_{next_ev.id}_2", dep2, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location,
                                  origin=pickup_wp.get("pickup_location", ""), static=pickup_wp.get("from_pickup_mins", 0))
                    else:
                        dep_time = max(ev_end_ts + buffer_after * 60, next_ev_start_ts - (edge.get("travel_mins", 0) + buffer_before + 5) * 60)
                        add_notif(f"route_{ev_id}_{next_ev.id}", dep_time, f"Drive to {next_ev.location.split(',')[0]}", next_ev.location,
                                  origin=ev.location, static=edge.get("travel_mins", 0))
                        
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

        daily_hash = hash_events(events_to_solve_by_date[date_str], assist_map=assist_map)
        daily_events_to_solve = events_to_solve_by_date[date_str]

        # Check cache
        daily_cache = storage.get_cached_daily_schedule(date_str)
        if daily_cache and daily_cache.get('events_hash') == daily_hash and not force_refresh and not draft:
            sched = daily_cache.get('schedule', {})

            # Update previous_assignments so subsequent days know what was assigned!
            previous_assignments.update(sched.get("assignments", {}))

            base_schedules[date_str] = {
                "assignments": sched.get("assignments", {}),
                # Every key Pass 3 persists must survive this reuse branch —
                # omitting one silently erases it from the daily cache on the
                # next routine refresh (how car_assignments kept vanishing).
                "car_assignments": sched.get("car_assignments", {}),
                "assist_assignments": sched.get("assist_assignments", {}),
                "unassigned": sched.get("unassigned", []),
                "lateness_warnings": sched.get("lateness_warnings", []),
                "ghost_assignments": sched.get("ghost_assignments", {}),
                "ghost_drivers": sched.get("ghost_drivers", []),
                "events": daily_events_to_solve,
                "true_unassigned": sched.get("true_unassigned", []),
                "conflicts": sched.get("conflicts", [])
            }
            continue

        # Outside hands (load arc A1): an event somebody outside this household
        # is covering leaves the optimisation ENTIRELY — not assignable, not
        # unassigned, not ghost-eligible. It is still drawn (it is a real thing
        # happening today), so it goes back into `events` below; it simply is
        # not ours to solve. This is the whole point of the feature: outside
        # help removes load, and the app previously had no way to be told so.
        # Resolved to INSTANCE keys here, once. A series row covers every
        # occurrence, but the payload every downstream surface reads — digest,
        # coverage report, timeline, phone — is keyed by the event in front of
        # it, so the recurrence model stops at this line instead of leaking
        # into six consumers.
        daily_assist = {}
        for e in daily_events_to_solve:
            cid = _assist_svc.coverage_for(assist_map, e)
            if cid:
                daily_assist[e.id] = cid
        assist_events = [e for e in daily_events_to_solve if e.id in daily_assist]
        if daily_assist:
            daily_events_to_solve = [e for e in daily_events_to_solve
                                     if e.id not in daily_assist]

        # An optional event decided 'skip' leaves the optimisation the same
        # way an assist-covered one does: not assignable, not unassigned,
        # nobody chased. Still drawn — it is a real thing on the calendar,
        # worn as skipped.
        skipped_optional = [e for e in daily_events_to_solve
                            if getattr(e, 'optional_decision', None) == 'skip']
        if skipped_optional:
            daily_events_to_solve = [e for e in daily_events_to_solve
                                     if getattr(e, 'optional_decision', None) != 'skip']

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
            car_assignments = {}
            if daily_cache and 'schedule' in daily_cache and 'assignments' in daily_cache['schedule']:
                assignments = dict(daily_cache['schedule']['assignments'])
                car_assignments = dict(daily_cache['schedule'].get('car_assignments', {}))
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
            assignments, unassigned, lateness_warnings, car_assignments = matcher.solve_schedule(
                daily_events_to_solve, drivers, rules, priority_rules, overrides=overrides, previous_assignments=previous_assignments, driver_events=driver_events_map, passengers=passengers, trip_metadata=trip_metadata, theme=default_theme, load_balancing=load_balancing, load_balancing_metric=load_balancing_metric, cars=cars
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
            "car_assignments": car_assignments,
            "assist_assignments": daily_assist,
            "unassigned": unassigned,
            "lateness_warnings": lateness_warnings,
            "ghost_assignments": ghost_assignments,
            "ghost_drivers": ghost_drivers,
            # Covered and skipped events go back in: the solver ignored them,
            # but they are real things happening today and the timeline must
            # draw them.
            "events": daily_events_to_solve + assist_events + skipped_optional,
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
            "car_assignments": base.get('car_assignments', {}),
            "assist_assignments": base.get('assist_assignments', {}),
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
                    a, u, lw, _ca = matcher.solve_schedule(d_evs, drvs, rls, prls, overrides=ovr, previous_assignments=prev, driver_events=d_map, passengers=paxs, trip_metadata=meta, theme=t, load_balancing=load_balancing, load_balancing_metric=load_balancing_metric)
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
def update_drive_status(status: DriveStatus, background_tasks: BackgroundTasks):
    storage.mark_drive_status(status.leg_id, status.status)
    if status.status == 'in_progress':
        # K2: tell child passengers their ride is on the way (deduped to the
        # first leg per event per day inside the helper).
        background_tasks.add_task(_notify_kids_ride_started,
                                  _leg_event_id(status.leg_id))
    return {"status": "ok"}

class PrepStatusRequest(BaseModel):
    event_id: str            # PARENT event instance id (leg suffixes stripped client-side)
    confirmed: bool = True
    member_id: Optional[str] = None

@app.post("/api/prep_status")
def update_prep_status(req: PrepStatusRequest):
    storage.set_prep_confirmed(req.event_id, req.confirmed, req.member_id)
    return {"status": "ok"}

def _prep_by_event(events):
    """{event_id: [items]} for schedule-payload events with matching enabled
    prep kits. Computed per request like completed_drives — kit edits show up
    without a schedule-cache rebuild. Pure-Python matching, no LLM."""
    from services import prep_kits
    try:
        kits = [k for k in storage.get_prep_kits() if k.get('enabled') is not False]
        if not kits:
            return {}
        pax = prep_kits.passenger_objs()
        out = {}
        for ev in events or []:
            if not isinstance(ev, dict):
                ev = ev.dict() if hasattr(ev, 'dict') else vars(ev)
            if ev.get('event_type') in ('errand', 'background_trip'):
                continue
            items = prep_kits.items_for_event(ev, kits, pax)
            if items:
                out[str(ev.get('id'))] = items
        return out
    except Exception as pe:
        logger.error(f"prep_by_event failed: {pe}")
        return {}

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
                        combined_car_assignments = {}
                        combined_assist_assignments = {}
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

                            for e_id, c_id in sched.get('car_assignments', {}).items():
                                combined_car_assignments[e_id] = c_id


                            for e_id in sched.get('unassigned', []):
                                if e_id not in combined_unassigned:
                                    combined_unassigned.append(e_id)
                            
                            for lw in sched.get('lateness_warnings', []):
                                if lw not in combined_lateness_warnings:
                                    combined_lateness_warnings.append(lw)
                            
                            for e_id, d_id in sched.get('ghost_assignments', {}).items():
                                combined_ghost_assignments[e_id] = d_id

                            for e_id, c_id in sched.get('assist_assignments', {}).items():
                                combined_assist_assignments[e_id] = c_id

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
                                "car_assignments": combined_car_assignments,
                                "assist_assignments": combined_assist_assignments,
                                # decorate(): carries `helps_with` so the drives page can offer
            # only the people who drive, without a second synonym table in JS.
            "assist_contacts": _assist_svc.decorate(
                storage.get_assist_contacts(include_inactive=True)),
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
                                "cars": [c for c in storage.get_all_cars() if not c.get('is_disabled')],
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
                cached["prep_by_event"] = _prep_by_event(cached.get("events"))
                cached["prep_confirmed"] = storage.get_confirmed_preps()
                cached["solving_dates"] = schedule_coordinator.get_solving_dates()
                # Identity colors at serve time: cached metadata/driver colors
                # predate any color edit made since the cache was built.
                cached["calendar_metadata"] = _apply_identity_colors(cached.get("calendar_metadata") or {})
                cached["drivers"] = _identity_driver_colors(cached.get("drivers"))
                # The legend roster likewise: the combined-daily and custom-range
                # caches are assembled from per-day solver output, which knows
                # about drivers and passengers and nothing else. Without this a
                # person with no profile lost their chip on every warm response —
                # which is the whole surface this exists for.
                cached["members"] = _calendar_legend_members()
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
                res["prep_by_event"] = _prep_by_event(res.get("events"))
                res["prep_confirmed"] = storage.get_confirmed_preps()
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

