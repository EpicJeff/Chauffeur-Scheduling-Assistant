"""Tests for school-bus support (bus arc B1).

Load-bearing properties: the bus launch line appears only for opted-in kids
on weekdays and yields to any morning car ride; live HCTB estimates only
apply for TODAY while the bus is actually out, and lateness is reported only
beyond the jitter threshold; the dismissal push says "bus home" only for
bus-configured kids (silence stands for everyone else); the kid digest leads
with the bus line even when the day has no car rides.

Run from chauffeur/:  python tests/test_bus.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import bus, storage

TODAY = datetime.date.today()
# A guaranteed weekday relative to today (for date-shape tests use Monday).
MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())
SATURDAY = MONDAY + datetime.timedelta(days=5)

KID = {"id": "kid1", "name": "Addison Smith", "role": "child",
       "school_hours_start": "08:00", "school_hours_end": "15:00",
       "bus_am_stop_time": "07:22", "bus_walk_mins": 5}


def scenario_static_morning_launch():
    with mock.patch.object(bus, 'bus_active', return_value=False):
        launch = bus.morning_launch(dict(KID), MONDAY.isoformat())
    check(launch is not None, "opted-in kid gets a bus launch on a weekday")
    check(launch['bus'] is True and launch['driver'] is None, "bus launch shape")
    check(launch['leave_label'] == '7:17 AM', f"leave = stop − walk ({launch['leave_label']})")
    check(launch['bus_stop_label'] == '7:22 AM', "stop label from static time")
    check(launch['bus_live'] is False and launch['bus_late_mins'] is None,
          "no live claims without HCTB")

    check(bus.morning_launch(dict(KID), SATURDAY.isoformat()) is None,
          "no bus line on weekends")
    no_bus = {**KID, "bus_am_stop_time": None}
    check(bus.morning_launch(no_bus, MONDAY.isoformat()) is None,
          "no config -> no bus line (opt-in)")


def scenario_car_ride_wins_the_morning():
    morning_ride = {"start": datetime.datetime.combine(MONDAY, datetime.time(7, 40)).isoformat()}
    afternoon_ride = {"start": datetime.datetime.combine(MONDAY, datetime.time(16, 0)).isoformat()}
    with mock.patch.object(bus, 'bus_active', return_value=False):
        check(bus.morning_launch(dict(KID), MONDAY.isoformat(), [morning_ride]) is None,
              "a morning car ride suppresses the bus line")
        check(bus.morning_launch(dict(KID), MONDAY.isoformat(), [afternoon_ride]) is not None,
              "an afternoon ride does not")


def scenario_live_estimate_only_today_and_active():
    live_t = datetime.time(7, 29)
    with mock.patch.object(bus, 'bus_active', return_value=True), \
         mock.patch.object(bus, 'live_stop_time', return_value=live_t):
        launch = bus.morning_launch(dict(KID), TODAY.isoformat())
        if TODAY.weekday() < 5:
            check(launch['bus_live'] is True, "live estimate used while bus is out today")
            check(launch['bus_late_mins'] == 7, "7 min beyond schedule reported as late")
            check(launch['bus_stop_label'] == '7:29 AM', "live time shown")
        future = MONDAY + datetime.timedelta(days=7)
        launch2 = bus.morning_launch(dict(KID), future.isoformat())
        check(launch2['bus_live'] is False, "live never applies to a future date")
    # Jitter below the threshold is not "late"
    with mock.patch.object(bus, 'bus_active', return_value=True), \
         mock.patch.object(bus, 'live_stop_time', return_value=datetime.time(7, 24)):
        launch = bus.morning_launch(dict(KID), TODAY.isoformat())
        if TODAY.weekday() < 5:
            check(launch['bus_late_mins'] is None, "2-min wobble is not news")


def scenario_digest_line_wording():
    with mock.patch.object(bus, 'bus_active', return_value=False):
        launch = bus.morning_launch(dict(KID), MONDAY.isoformat())
    line = bus.digest_line(launch)
    check(line == "🚌 Bus at 7:22 AM — out the door by 7:17 AM", f"digest wording ({line})")
    launch['bus_late_mins'] = 6
    check("no rush" in bus.digest_line(launch), "lateness framed as permission to relax")


def scenario_dismissal_line():
    check(bus.dismissal_line({"name": "NoBus Kid"}) is None,
          "no bus config -> dismissal silence stands")
    with mock.patch.object(bus, 'bus_active', return_value=False):
        am_only = bus.dismissal_line(dict(KID))
        check(am_only == "You're riding the bus home today.", "am-only config reassures")
        with_pm = bus.dismissal_line({**KID, "bus_pm_stop_time": "15:45"})
        check("3:45 PM" in with_pm, "static PM drop time named")
    with mock.patch.object(bus, 'bus_active', return_value=True), \
         mock.patch.object(bus, 'live_stop_time', return_value=datetime.time(15, 51)):
        live = bus.dismissal_line({**KID, "bus_pm_stop_time": "15:45"})
        check("3:51 PM" in live, "live PM estimate wins while the bus is out")


def scenario_dismissal_push_bus_branch():
    import main
    for t in (storage.members_table, storage.cache_table, storage.app_state_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member(dict(KID, is_child=True))
    kid = storage.get_member("kid1")
    dismissal = datetime.datetime.combine(TODAY, datetime.time(15, 0))
    empty_day = {"rides": [], "due_soon": [], "launch": None}
    with mock.patch.object(main, 'member_day', return_value=empty_day), \
         mock.patch.object(bus, 'bus_active', return_value=False), \
         mock.patch.object(main, '_notify_member_lanes') as lanes:
        sent = main._send_school_end_push(kid, now=dismissal)
        check(sent is True and lanes.call_count == 1, "bus kid gets a dismissal push with no car ride")
        check(lanes.call_args[0][1] == "🚌 Bus home today", "bus dismissal title")
    storage.members_table.truncate()
    storage.add_member({"id": "kid2", "name": "Carless Kid", "role": "child",
                        "is_child": True, "school_hours_end": "15:00"})
    kid2 = storage.get_member("kid2")
    with mock.patch.object(main, 'member_day', return_value=empty_day), \
         mock.patch.object(main, '_notify_member_lanes') as lanes:
        sent = main._send_school_end_push(kid2, now=dismissal)
        check(sent is False and lanes.call_count == 0,
              "non-bus kid with no ride stays silent (original rule)")



# --- B2: the live morning layer -------------------------------------------

def _live_kid(**over):
    return {**KID, "bus_ready_lead_mins": 10, "bus_late_push": True, **over}


def scenario_live_chip_only_while_the_bus_is_rolling():
    """A chip saying "on the way" about a parked bus is worse than no chip,
    because somebody will believe it and leave the house."""
    plan = {"bus": True, "bus_live": False, "bus_stop_label": "7:22 AM",
            "leave_label": "7:17 AM"}
    seven = datetime.datetime.combine(MONDAY, datetime.time(7, 0))
    check(bus.live_chip(KID, plan, seven) is None,
          "a static plan produced a live chip")
    live = {**plan, "bus_live": True, "bus_where": "Elm & 3rd"}
    chip = bus.live_chip(KID, live, seven)
    check(chip and "On the way" in chip and "7:22 AM" in chip,
          f"live chip missing its facts: {chip}")
    check("Elm & 3rd" in chip, f"the chip dropped where the bus is: {chip}")
    # Same bus, same state, four in the afternoon: that route is taking
    # somebody else home and the morning wall should say nothing.
    afternoon = datetime.datetime.combine(MONDAY, datetime.time(16, 0))
    check(bus.live_chip(KID, live, afternoon) is None,
          "the morning chip fired outside the morning window")


def scenario_a_chip_without_a_location_still_says_the_useful_half():
    """Most districts expose an ETA and no address. On the way + when is
    almost all of the value; a chip that needs both would show for nobody."""
    seven = datetime.datetime.combine(MONDAY, datetime.time(7, 0))
    chip = bus.live_chip(KID, {"bus": True, "bus_live": True,
                               "bus_stop_label": "7:22 AM"}, seven)
    check(chip and "On the way" in chip, f"no chip without a location: {chip}")
    check("·  ·" not in chip and not chip.rstrip().endswith("·"),
          f"the chip left a dangling separator: {chip}")


def scenario_lateness_keeps_its_voice_in_the_chip():
    """B1 settled this and it is not to drift: lateness is PERMISSION TO
    RELAX, never urgency."""
    seven = datetime.datetime.combine(MONDAY, datetime.time(7, 0))
    chip = bus.live_chip(KID, {"bus": True, "bus_live": True, "bus_late_mins": 7,
                               "bus_stop_label": "7:29 AM"}, seven)
    check("no rush" in chip, f"the chip hurries a child: {chip}")


def scenario_get_ready_is_a_window_that_closes():
    """The loop runs every 30s, but a container restarts and a panel sleeps.
    A nudge to leave for a bus that has already gone is the one thing this
    must never send."""
    leave = datetime.datetime.combine(MONDAY, datetime.time(7, 17))
    launch = {"bus": True, "leave_at": leave.isoformat(),
              "bus_stop_label": "7:22 AM"}
    kid = _live_kid()
    check(bus.ready_push(kid, launch, leave - datetime.timedelta(minutes=20)) is None,
          "the nudge fired before its window opened")
    msg = bus.ready_push(kid, launch, leave - datetime.timedelta(minutes=8))
    check(msg and "8 min" in msg[1], f"the nudge did not say when: {msg}")
    at_leave = bus.ready_push(kid, launch, leave)
    check(at_leave and "now" in at_leave[1], f"at the deadline: {at_leave}")
    check(bus.ready_push(kid, launch, leave + datetime.timedelta(minutes=1)) is None,
          "the nudge fired after the bus had gone")


def scenario_the_lead_is_the_opt_in():
    """No separate enable switch: a switch beside a number is two ways to say
    the same thing, and the one that ships off is the one people forget."""
    leave = datetime.datetime.combine(MONDAY, datetime.time(7, 17))
    launch = {"bus": True, "leave_at": leave.isoformat(),
              "bus_stop_label": "7:22 AM"}
    now = leave - datetime.timedelta(minutes=5)
    check(bus.ready_push(KID, launch, now) is None,
          "a kid with no lead set got a push anyway")
    check(bus.ready_push(_live_kid(bus_ready_lead_mins=0), launch, now) is None,
          "a zero lead is not off")


def scenario_one_message_when_late_and_leaving():
    """Two pushes a minute apart about the same bus is how a phone gets
    muted, so the nudge carries the lateness itself."""
    leave = datetime.datetime.combine(MONDAY, datetime.time(7, 17))
    msg = bus.ready_push(_live_kid(), {"bus": True, "leave_at": leave.isoformat(),
                                       "bus_stop_label": "7:29 AM",
                                       "bus_late_mins": 7},
                         leave - datetime.timedelta(minutes=5))
    check("no rush" in msg[1] and "7 min" in msg[1],
          f"the nudge did not carry the lateness: {msg}")


def scenario_late_push_is_its_own_opt_in():
    """News and routine are different kinds of message, and a family may well
    want the news without the routine."""
    launch = {"bus": True, "bus_late_mins": 6, "bus_stop_label": "7:29 AM"}
    check(bus.late_push(KID, launch) is None,
          "the late push fired for a kid who never asked for it")
    msg = bus.late_push(_live_kid(), launch)
    check(msg and "no rush" in msg[1] and "6 min" in msg[1],
          f"late push wording: {msg}")
    check(bus.late_push(_live_kid(), {"bus": True, "bus_stop_label": "7:22 AM"}) is None,
          "a punctual bus produced a lateness push")


def scenario_the_location_sensor_refuses_nonsense():
    """A district's sensor might hold a cross-street, a road or a stop number.
    "on the way - 42" answers nothing, so obvious non-places are dropped."""
    def state(val):
        return mock.patch('services.ha_api.get_state', return_value={'state': val})
    with state('Elm & 3rd'):
        check(bus.bus_where(KID) == 'Elm & 3rd', "a real place was dropped")
    for junk in ('unknown', 'unavailable', '', '42', 'off'):
        with state(junk):
            check(bus.bus_where(KID) is None, f"junk state accepted: {junk!r}")


def scenario_where_is_only_read_while_the_bus_is_out():
    """A location read on every board poll, all day, for a parked bus is one
    HA request per panel per minute for nothing."""
    with mock.patch.object(bus, 'bus_active', return_value=False),             mock.patch.object(bus, 'bus_where') as where:
        bus.morning_launch(dict(KID), MONDAY.isoformat())
    check(not where.called, "the location sensor was read for a parked bus")



def scenario_every_b2_field_has_a_hand_path():
    """Standing rule: nothing is agent- or config-file-only. A field a parent
    cannot reach is a feature that does not exist for them."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = open(os.path.join(root, 'templates', 'config.html'),
               encoding='utf-8').read()
    for field in ('bus_ready_lead_mins', 'bus_late_push', 'bus_location_entity'):
        check(f'memberEdit.{field}' in cfg,
              f"{field} has no input on the member card")
        # Bound BOTH ways: an input that loads but never saves is the same
        # bug as no input at all, and looks like it worked.
        check(f'{field}: member.{field}' in cfg or f'{field}: !!member.{field}' in cfg,
              f"{field} is never loaded into the edit form")
        check(f'updates.{field}' in cfg, f"{field} is never saved")
    from models import schemas
    for field in ('bus_ready_lead_mins', 'bus_late_push', 'bus_location_entity'):
        check(field in schemas.FamilyMember.model_fields,
              f"{field} is not on the member model, so the PUT drops it")


SCENARIOS = [
    scenario_static_morning_launch,
    scenario_car_ride_wins_the_morning,
    scenario_live_estimate_only_today_and_active,
    scenario_digest_line_wording,
    scenario_dismissal_line,
    scenario_dismissal_push_bus_branch,
    scenario_live_chip_only_while_the_bus_is_rolling,
    scenario_a_chip_without_a_location_still_says_the_useful_half,
    scenario_lateness_keeps_its_voice_in_the_chip,
    scenario_get_ready_is_a_window_that_closes,
    scenario_the_lead_is_the_opt_in,
    scenario_one_message_when_late_and_leaving,
    scenario_late_push_is_its_own_opt_in,
    scenario_the_location_sensor_refuses_nonsense,
    scenario_where_is_only_read_while_the_bus_is_out,
    scenario_every_b2_field_has_a_hand_path,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
