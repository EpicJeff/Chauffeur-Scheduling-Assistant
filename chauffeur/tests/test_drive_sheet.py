"""The drive sheet: what it says, and what its position pings are allowed to do.

Two properties are load-bearing and everything here defends one of them.

  1. **The sheet never invents.** It is assembled from the leg id, the row the
     Start tap wrote, and the caches every other surface reads. A drive with no
     ETA says nothing about arrival time rather than guessing one, and a leg
     that carries its passengers never offers to tell them the car is outside.

  2. **A ping either completes the leg or says nothing.** It runs unattended,
     every forty-five seconds, from a moving car — so it uses the passive
     arrival rules (started leg, cached street-level pin, fresh precise fix,
     inside the tight radius) and it never prices a route. A false complete
     un-tracks a drive that is genuinely happening; a paid Directions call on a
     timer is a bill.

Run from chauffeur/:  python tests/test_drive_sheet.py
"""
import atexit
import datetime
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_drive_sheet_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import drive_arrival, drive_sheet, storage  # noqa: E402

# The pool, and a phone in its car park ~60 m off the pin.
POOL = (35.7327, -78.7811)
LOT = (35.7332, -78.7808)
ELSEWHERE = (35.79, -78.65)   # ~10 km away, mid-drive
NOW = datetime.datetime(2026, 8, 18, 16, 0, 0)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None


def _member(mid, name, **kw):
    doc = {"id": mid, "name": name, "color_code": "#3b82f6", "avatar": None,
           "bio": "", "can_drive": False, "is_child": False, "driver_id": None,
           "passenger_id": None, "ha_person_entity": None, "notify_service": None,
           "media_player_entity": None, "pin": None, "role": "parent",
           "created_at": time.time()}
    doc.update(kw)
    storage.add_member(doc)
    return doc


LILY = {}   # the member id storage mints for the passenger, per world


def _world(event_id="swim", location="Ancient Oaks Pool, Cary"):
    """A family, a pool, and a drive to collect a child from it.

    The child is added as a PASSENGER and left to the app's own overlay to
    turn into a member (add_passenger -> ensure_members), because that is how
    a real household's records come to exist and the roll call has to work
    against the ids that produces."""
    reset_db()
    storage.add_passenger({"id": "p_lily", "name": "Lily",
                           "calendar_ids": ["cal_lily"], "hashtags": []})
    lily = next(m for m in storage.get_all_members()
                if m.get("passenger_id") == "p_lily")
    storage.update_member(lily["id"], {"role": "child", "is_child": True})
    LILY["id"] = lily["id"]
    _member("m_jeff", "Jeff", driver_id="drv_jeff", can_drive=True, role="parent")
    _member("m_amy", "Amy", role="parent")
    storage.set_cached_schedule({
        "events": [{"id": event_id, "title": "Swim Practice",
                    "start": (NOW + datetime.timedelta(minutes=30)).isoformat(),
                    "end": (NOW + datetime.timedelta(minutes=90)).isoformat(),
                    "location": location, "calendar_ids": ["cal_lily"]}],
        "assignments": {event_id: "drv_jeff"},
        "car_assignments": {},
        "matched_rules": {},
    })


def scenario_the_sheet_says_what_the_drive_is():
    _world()
    storage.mark_drive_status("init_swim_1", "in_progress",
                              eta_ts=(NOW + datetime.timedelta(minutes=12)).timestamp())
    d = drive_sheet.sheet("init_swim_1", now=NOW)

    check(d["destination"]["address"] == "Ancient Oaks Pool, Cary",
          f"the address comes off the leg's event, got {d['destination']}")
    check(d["eta_label"], "the ETA the Start tap priced is said out loud")
    check(d["status"] == "in_progress", "the leg's own status rides along")
    check([p["name"] for p in d["passengers"]] == ["Lily"],
          f"the child bound to the event is on the roll call, got {d['passengers']}")
    check(d["passengers"][0]["aboard"] is None,
          "nobody has been tapped yet, which is the normal case")
    check(d["driver_name"] == "Jeff", "the driver resolves through the assignment")


def scenario_no_eta_says_nothing_about_arrival():
    _world()
    storage.mark_drive_status("init_swim_1", "in_progress")
    d = drive_sheet.sheet("init_swim_1", now=NOW)
    check(d["eta_ts"] is None and d["eta_label"] is None,
          "a drive whose start could not be priced makes no claim about arrival")


def scenario_only_a_drive_toward_the_waiting_offers_to_tell_them():
    _world()
    toward = drive_sheet.sheet("init_swim_1", now=NOW)      # to the pickup point
    carrying = drive_sheet.sheet("init_swim_2", now=NOW)    # them aboard, onward

    keys = lambda d: {m["key"] for m in d["messages"]}
    check("outside" in keys(toward) and "come_out" in keys(toward),
          f"driving toward a waiting kid can say so, got {keys(toward)}")
    check(keys(carrying) == {"on_my_way"},
          f"with the kid in the back seat only the neutral line survives, "
          f"got {keys(carrying)}")
    check(toward["toward_waiting"] is True and carrying["toward_waiting"] is False,
          "and the sheet says which kind of drive this is")


def scenario_the_audience_is_the_riders_and_the_other_parent():
    _world()
    names = drive_sheet.sheet("init_swim_1", now=NOW)["audience"]
    check("Lily" in names, f"the kid being collected hears it, got {names}")
    check("Amy" in names, f"so does the parent who is not driving, got {names}")
    check("Jeff" not in names, f"the driver is not told about their own drive, got {names}")


def scenario_a_quick_message_lands_in_the_chat():
    _world()
    posted = []
    import services.agent_tools_v2 as v2
    with mock.patch.object(v2, "_post_chat_message",
                           side_effect=lambda ch, s, b, card=None, context=None: posted.append((ch["id"], b))):
        out = drive_sheet.send_quick_message("init_swim_1", "outside",
                                             storage.get_member("m_jeff"))
    check(out["status"] == "ok", f"the send reports success, got {out}")
    check("Jeff is outside for" in out["body"],
          f"the line names the driver and the drive, got {out['body']}")
    check(len(posted) == 2, f"one DM per recipient, got {len(posted)}")
    check(len({ch for ch, _b in posted}) == 2, "and they are separate threads")


def scenario_an_unknown_message_is_refused():
    _world()
    out = drive_sheet.send_quick_message("init_swim_1", "hurry_up",
                                         storage.get_member("m_jeff"))
    check(out["status"] == "error", "the canned list is the whole vocabulary")


def scenario_roll_call_cycles_and_forgets():
    _world()
    storage.set_roll_call("init_swim_1", LILY["id"], True)
    check(drive_sheet.sheet("init_swim_1", now=NOW)["passengers"][0]["aboard"] is True,
          "aboard is remembered")
    storage.set_roll_call("init_swim_1", LILY["id"], False)
    check(drive_sheet.sheet("init_swim_1", now=NOW)["passengers"][0]["aboard"] is False,
          "not-here is a different answer from unanswered")
    storage.set_roll_call("init_swim_1", LILY["id"], None)
    check(drive_sheet.sheet("init_swim_1", now=NOW)["passengers"][0]["aboard"] is None,
          "and a third tap takes the claim back")


def scenario_roll_call_never_touches_the_drive():
    _world()
    storage.mark_drive_status("init_swim_1", "in_progress", eta_ts=123.0)
    storage.set_roll_call("init_swim_1", LILY["id"], True)
    row = storage.get_drive_status("init_swim_1")
    check(row["status"] == "in_progress" and row["eta_ts"] == 123.0,
          f"the roll call rides on the leg row without disturbing it, got {row}")


def scenario_the_low_tank_is_flagged_before_the_drive():
    _world()
    storage.add_car({"id": "car1", "name": "The Van", "icon": "🚐",
                     "ha_fuel_entity": "sensor.van_fuel"})
    sched = storage.get_cached_schedule()
    sched["car_assignments"] = {"swim": "car1"}
    storage.set_cached_schedule(sched)
    import services.cars as cars_svc
    with mock.patch.object(cars_svc, "car_levels",
                           return_value={"fuel_pct": 9, "battery_pct": None,
                                         "range": 30}):
        d = drive_sheet.sheet("init_swim_1", now=NOW)
    check(d["car"]["name"] == "The Van", "the assigned car is named")
    check(d["car"]["warn"] == "Fuel 9%",
          f"and a tank under the household's threshold is flagged, got {d['car']}")


def _add_drive(ev_id, title, offset):
    sched = storage.get_cached_schedule()
    sched["events"].append({"id": ev_id, "title": title,
                            "start": (NOW + offset).isoformat(),
                            "end": (NOW + offset + datetime.timedelta(hours=1)).isoformat(),
                            "location": "Music & Arts", "calendar_ids": []})
    sched["assignments"][ev_id] = "drv_jeff"
    storage.set_cached_schedule(sched)


def scenario_the_next_drive_is_the_one_after_this_one():
    _world()
    _add_drive("guitar", "Guitar", datetime.timedelta(hours=3))
    nxt = drive_sheet.sheet("init_swim_1", now=NOW)["next_drive"]
    check(nxt and nxt["title"] == "Guitar",
          f"the driver's following run is named, got {nxt}")
    check("event_id" in nxt and "leg_id" not in nxt,
          "display only — it never guesses a leg id to tap")


def scenario_tomorrows_drive_is_not_whats_next():
    """The schedule cache holds days either side. A sheet held at six in the
    evening answering with tomorrow morning's school run reads as 'you are
    not finished' to somebody who is."""
    _world()
    _add_drive("school", "School Run", datetime.timedelta(hours=17))
    d = drive_sheet.sheet("init_swim_1", now=NOW)
    check(d["next_drive"] is None,
          f"tomorrow is not next, got {d['next_drive']}")
    check(d["day_done"] is True,
          "and the sheet can say the day is done instead of going quiet")


def scenario_today_beats_tomorrow_when_there_is_both():
    _world()
    _add_drive("school", "School Run", datetime.timedelta(hours=17))
    _add_drive("guitar", "Guitar", datetime.timedelta(hours=3))
    d = drive_sheet.sheet("init_swim_1", now=NOW)
    check(d["next_drive"]["title"] == "Guitar",
          f"today's remaining drive wins, got {d['next_drive']}")
    check(d["day_done"] is False, "and the day is plainly not over")


def scenario_a_drive_with_nothing_after_it_says_so():
    _world()
    d = drive_sheet.sheet("init_swim_1", now=NOW)
    check(d["next_drive"] is None,
          "the last drive of the day has no next line rather than a wrong one")
    check(d["day_done"] is True, "it says the day is done instead")


def scenario_an_unassigned_leg_claims_nothing_about_the_day():
    """No driver resolves — so there is no 'last drive of the day' to claim
    either. Silence, not a cheerful wrong answer."""
    _world()
    sched = storage.get_cached_schedule()
    sched["assignments"] = {}
    storage.set_cached_schedule(sched)
    d = drive_sheet.sheet("init_swim_1", now=NOW)
    check(d["next_drive"] is None and d["day_done"] is False,
          f"nothing known means nothing said, got day_done={d['day_done']}")


def scenario_an_unknown_leg_degrades_to_an_empty_sheet():
    _world()
    d = drive_sheet.sheet("init_nothing_at_all", now=NOW)
    check(d["passengers"] == [] and d["car"] is None and d["eta_label"] is None,
          "a leg the caches have never heard of draws an empty sheet, not an error")


# --- the position lane -------------------------------------------------------

def _geocode(latlon, precision="exact"):
    return {"lat": latlon[0], "lon": latlon[1], "precision": precision}


def scenario_a_ping_at_the_destination_completes_the_leg():
    _world()
    storage.mark_drive_status("init_swim", "in_progress")
    with mock.patch.object(storage, "get_cached_geocode", return_value=_geocode(POOL)):
        out = drive_sheet.record_ping("m_jeff", "init_swim", LOT[0], LOT[1],
                                      accuracy=15, now_ts=NOW.timestamp())
    check(out["completed"] is True, f"arriving closes the leg, got {out}")
    check(storage.get_drive_status("init_swim")["status"] == "completed",
          "and the row says so")


def scenario_a_ping_mid_drive_completes_nothing():
    _world()
    storage.mark_drive_status("init_swim", "in_progress")
    with mock.patch.object(storage, "get_cached_geocode", return_value=_geocode(POOL)):
        out = drive_sheet.record_ping("m_jeff", "init_swim", ELSEWHERE[0],
                                      ELSEWHERE[1], accuracy=15,
                                      now_ts=NOW.timestamp())
    check(out["completed"] is False, "ten kilometres away is not arrival")
    check(storage.get_drive_status("init_swim")["status"] == "in_progress",
          "the drive is left exactly as it was")


def scenario_a_vague_fix_proves_nothing():
    _world()
    storage.mark_drive_status("init_swim", "in_progress")
    with mock.patch.object(storage, "get_cached_geocode", return_value=_geocode(POOL)):
        out = drive_sheet.record_ping("m_jeff", "init_swim", LOT[0], LOT[1],
                                      accuracy=2000, now_ts=NOW.timestamp())
    check(out["completed"] is False,
          "a two-kilometre cell fix at the pin still proves nothing")


def scenario_a_city_pin_proves_nothing():
    _world()
    storage.mark_drive_status("init_swim", "in_progress")
    with mock.patch.object(storage, "get_cached_geocode",
                           return_value=_geocode(POOL, precision="city")):
        out = drive_sheet.record_ping("m_jeff", "init_swim", LOT[0], LOT[1],
                                      accuracy=15, now_ts=NOW.timestamp())
    check(out["completed"] is False,
          "'arrived in Cary' is not 'arrived at the pool'")


def scenario_a_ping_never_starts_a_leg_nobody_started():
    _world()
    with mock.patch.object(storage, "get_cached_geocode", return_value=_geocode(POOL)):
        out = drive_sheet.record_ping("m_jeff", "init_swim", LOT[0], LOT[1],
                                      accuracy=15, now_ts=NOW.timestamp())
    check(out["completed"] is False,
          "arrival only ever closes a loop a human opened")


def scenario_a_ping_never_prices_a_route():
    _world()
    storage.mark_drive_status("init_swim", "in_progress")
    from services import maps
    with mock.patch.object(storage, "get_cached_geocode", return_value=_geocode(POOL)), \
            mock.patch.object(maps, "get_route_geometry") as route:
        drive_sheet.record_ping("m_jeff", "init_swim", ELSEWHERE[0], ELSEWHERE[1],
                                accuracy=15, now_ts=NOW.timestamp())
    check(route.call_count == 0,
          "the timer lane pays for no Directions call, ever")


def scenario_the_position_is_stored_for_everything_else_to_read():
    _world()
    drive_sheet.record_ping("m_jeff", None, LOT[0], LOT[1], accuracy=15,
                            now_ts=NOW.timestamp())
    pos = storage.get_member_position("m_jeff")
    check(pos and pos["latitude"] == LOT[0] and pos["source"] == "app",
          f"the fix lands on the member, got {pos}")
    storage.clear_member_position("m_jeff")
    check(storage.get_member_position("m_jeff") is None, "and can be dropped")


def scenario_the_app_fix_is_a_source_arrival_can_see():
    """The whole reason the sheet earns a wake lock: a household with no HA
    companion app had no position at all, so nothing ever self-completed."""
    _world()
    storage.set_member_position("m_jeff", LOT[0], LOT[1], 15, NOW.timestamp())
    members = {"drv_jeff": storage.get_member("m_jeff")}
    pos = drive_arrival._driver_position("drv_jeff", "swim", {}, members,
                                         NOW.timestamp())
    check(pos and round(pos[0], 4) == round(LOT[0], 4),
          f"the app's own fix answers when nothing else can, got {pos}")


def scenario_a_stale_app_fix_loses_to_a_live_ha_one():
    _world()
    storage.update_member("m_jeff", {"ha_person_entity": "person.jeff"})
    old = NOW.timestamp() - 3600
    storage.set_member_position("m_jeff", ELSEWHERE[0], ELSEWHERE[1], 15, old)
    fresh = datetime.datetime.now(datetime.timezone.utc).isoformat()
    import services.ha_api as ha_api
    members = {"drv_jeff": storage.get_member("m_jeff")}
    with mock.patch.object(ha_api, "get_state", return_value={
            "state": "not_home", "last_updated": fresh,
            "attributes": {"latitude": LOT[0], "longitude": LOT[1],
                           "gps_accuracy": 12}}):
        pos = drive_arrival._driver_position("drv_jeff", "swim", {}, members,
                                             NOW.timestamp())
    check(pos and round(pos[0], 4) == round(LOT[0], 4),
          f"an hour-old app fix does not outrank a live tracker, got {pos}")


SCENARIOS = [
    scenario_the_sheet_says_what_the_drive_is,
    scenario_no_eta_says_nothing_about_arrival,
    scenario_only_a_drive_toward_the_waiting_offers_to_tell_them,
    scenario_the_audience_is_the_riders_and_the_other_parent,
    scenario_a_quick_message_lands_in_the_chat,
    scenario_an_unknown_message_is_refused,
    scenario_roll_call_cycles_and_forgets,
    scenario_roll_call_never_touches_the_drive,
    scenario_the_low_tank_is_flagged_before_the_drive,
    scenario_the_next_drive_is_the_one_after_this_one,
    scenario_tomorrows_drive_is_not_whats_next,
    scenario_today_beats_tomorrow_when_there_is_both,
    scenario_a_drive_with_nothing_after_it_says_so,
    scenario_an_unassigned_leg_claims_nothing_about_the_day,
    scenario_an_unknown_leg_degrades_to_an_empty_sheet,
    scenario_a_ping_at_the_destination_completes_the_leg,
    scenario_a_ping_mid_drive_completes_nothing,
    scenario_a_vague_fix_proves_nothing,
    scenario_a_city_pin_proves_nothing,
    scenario_a_ping_never_starts_a_leg_nobody_started,
    scenario_a_ping_never_prices_a_route,
    scenario_the_position_is_stored_for_everything_else_to_read,
    scenario_the_app_fix_is_a_source_arrival_can_see,
    scenario_a_stale_app_fix_loses_to_a_live_ha_one,
]


def scenario_the_hand_path_is_on_the_screen():
    """Every capability here has to be reachable by hand, not only by the
    agent — and these are hand-only, so the buttons ARE the feature."""
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates', 'app.html')
    app = open(tpl, encoding='utf-8').read()
    for fn in ('cycleRollCall(', 'sendQuickMessage(', 'sendMyEta(', 'tapArrived(',
               'toggleDriveLive(', 'toggleDrivePrep('):
        check(fn in app, f"{fn} is wired to something tappable")
    check('Last drive of the day' in app and 'day_done' in app,
          "a finished day says so rather than showing tomorrow")
    check('Send my ETA' in app and 'Arrived' in app and "Everybody in?" in app,
          "the sheet says these things in words a driver reads at a glance")
    check('maybeResumeDriveSheet' in app and 'DRIVE_RESUME_KEY' in app,
          "a killed app comes back to the drive it was on")
    check('wakeLock' in app and 'DRIVE_PING_MS' in app,
          "the screen stays awake and the position keeps reporting")
    check('Not Staying — Schedule Pick-up' in app and 'Mark as Completed' in app,
          "and nothing the old action sheet could do has been taken away")


SCENARIOS.append(scenario_the_hand_path_is_on_the_screen)


if __name__ == "__main__":
    failures = 0
    for s in SCENARIOS:
        try:
            s()
            print(f"  ok  {s.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {s.__name__}: {e}")
    print(f"\n{len(SCENARIOS) - failures}/{len(SCENARIOS)} drive-sheet scenarios passed")
    sys.exit(1 if failures else 0)
