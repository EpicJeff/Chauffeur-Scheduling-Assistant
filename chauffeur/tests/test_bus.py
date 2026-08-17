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



def scenario_the_autodiscovered_names_are_the_ones_hctb_publishes():
    """A default entity name that nothing publishes is a feature that silently
    never fires — and it cannot be caught by watching the wall, because the
    absence looks exactly like "the bus has no location today".

    HCTB names the DEVICE "{First} Bus" and its keys are bare (`address`,
    `am_stop_arrival_time`), so Home Assistant builds `sensor.{first}_bus_*`.
    The address one was first written as `_bus_location`, which is a name from
    nowhere."""
    seen = {}

    def fake_get_state(entity_id):
        seen['id'] = entity_id
        return {'state': 'Elm & 3rd'}

    with mock.patch('services.ha_api.get_state', side_effect=fake_get_state):
        bus.bus_where({"name": "John Smith"})
    check(seen['id'] == 'sensor.john_bus_address',
          f"the location default is not what HCTB publishes: {seen['id']}")
    # And the override still wins, which is how every other platform plugs in.
    with mock.patch('services.ha_api.get_state', side_effect=fake_get_state):
        bus.bus_where({"name": "John Smith",
                       "bus_location_entity": "sensor.somewhere_else"})
    check(seen['id'] == 'sensor.somewhere_else',
          f"an explicit location entity was ignored: {seen['id']}")


def scenario_the_stop_time_is_required_even_with_a_live_tracker():
    """It is the opt-in AND the baseline, and both matter: nothing else says
    which children ride a bus, and lateness is live-minus-static, so a kid
    with a perfect HCTB feed and no stop time has no bus feature at all."""
    perfect_feed = {**KID, "bus_am_stop_time": None}
    with mock.patch.object(bus, 'bus_active', return_value=True),             mock.patch.object(bus, 'live_stop_time',
                              return_value=datetime.time(7, 30)):
        check(bus.morning_launch(perfect_feed, MONDAY.isoformat()) is None,
              "a live tracker alone turned the bus feature on")



# --- B3: the morning as EVENTS ---------------------------------------------

def scenario_the_stop_is_never_guessed():
    """Every other live reading composes an HCTB name from the first name.
    The stop does not, and that is the point: it is usually an HA ZONE a
    parent drew on a map, and a zone's name is a household's own word. This
    is the third bug of that shape avoided rather than shipped."""
    check(bus.stop_position(dict(KID)) is None,
          "a member with no stop entity resolved one anyway")
    with mock.patch('services.ha_api.get_state',
                    return_value={'state': 'zoning',
                                  'attributes': {'latitude': 35.7, 'longitude': -78.8}}):
        got = bus.stop_position({**KID, 'bus_stop_entity': 'zone.bus_stop'})
    check(got == (35.7, -78.8), f"a zone's coordinates were not read: {got}")


def scenario_near_home_needs_a_radius_and_two_ends():
    """The radius IS the opt-in, and a missing end is not a reason to fire:
    an unknown distance must never read as zero."""
    at_home = {'state': 'x', 'attributes': {'latitude': 35.0, 'longitude': -78.0}}
    with mock.patch.object(bus, '_home_coords', return_value=(35.0, -78.0)),             mock.patch('services.ha_api.get_state', return_value=at_home):
        check(bus.near_home(dict(KID)) is False,
              "a kid with no radius set was reported as near")
        check(bus.near_home({**KID, 'bus_near_radius_m': 500}) is True,
              "the bus at the house was not near")
    far = {'state': 'x', 'attributes': {'latitude': 36.0, 'longitude': -78.0}}
    with mock.patch.object(bus, '_home_coords', return_value=(35.0, -78.0)),             mock.patch('services.ha_api.get_state', return_value=far):
        check(bus.near_home({**KID, 'bus_near_radius_m': 500}) is False,
              "a bus 100km away was reported as near")
    # No home address set: the trigger simply never fires rather than
    # guessing where a family lives.
    with mock.patch.object(bus, '_home_coords', return_value=None),             mock.patch('services.ha_api.get_state', return_value=at_home):
        check(bus.near_home({**KID, 'bus_near_radius_m': 500}) is False,
              "an unknown home resolved to a distance anyway")


def scenario_the_events_have_something_to_say_out_loud():
    """A phone in another room is not how you tell a seven-year-old to put
    their shoes on, so each event carries a SPOKEN form as well as a push."""
    for msg in (bus.route_start_message([dict(KID)]), bus.near_message([dict(KID)])):
        check(len(msg) == 3, f"an event has no spoken form: {msg}")
        title, body, spoken = msg
        check(title and body and spoken, f"an empty part: {msg}")
        check('Addison' in spoken, f"the spoken form does not name the kid: {spoken}")
        # Pushes go to the kid's own phone; the room hears it about them.
        check('Addison' not in body, f"the push talks about them in the third person: {body}")


def scenario_speaking_is_opt_in_per_child():
    """A house with a sleeping baby should not have to accept a talking
    kitchen to get a phone notification."""
    check(bus.announce_room(dict(KID)) is None, "silence is not the default")
    check(bus.announce_room({**KID, 'bus_announce_room': ' Kitchen '}) == 'Kitchen',
          "the room is not read (or not trimmed)")


def scenario_every_b3_field_has_a_hand_path():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = open(os.path.join(root, 'templates', 'config.html'), encoding='utf-8').read()
    from models import schemas
    for field in ('bus_tracker_entity', 'bus_stop_entity', 'bus_route_push',
                  'bus_near_radius_m', 'bus_near_zone', 'bus_announce_room',
                  'bus_number_entity'):
        check(f'memberEdit.{field}' in cfg, f"{field} has no input")
        check(f'{field}: member.{field}' in cfg or f'{field}: !!member.{field}' in cfg,
              f"{field} is never loaded")
        check(f'updates.{field}' in cfg, f"{field} is never saved")
        check(field in schemas.FamilyMember.model_fields,
              f"{field} is not on the model, so the PUT drops it")



def scenario_a_zone_is_already_a_geofence():
    """The best thing about pointing at a zone is that a zone carries its own
    radius: a parent drags a circle onto a map in HA and there is no number to
    type here and no unit to get wrong. Whichever zone they point at is the
    trigger — the stop, the corner, the end of the street — and the app has no
    business insisting which."""
    zone = {'state': 'zoning',
            'attributes': {'latitude': 35.0, 'longitude': -78.0, 'radius': 400}}
    inside = {'state': 'x', 'attributes': {'latitude': 35.001, 'longitude': -78.0}}
    outside = {'state': 'x', 'attributes': {'latitude': 35.05, 'longitude': -78.0}}
    kid = {**KID, 'bus_near_zone': 'zone.bus_stop'}

    def states(bus_state):
        def get(entity_id):
            return zone if entity_id.startswith('zone.') else bus_state
        return mock.patch('services.ha_api.get_state', side_effect=get)

    with states(inside):
        check(bus.bus_is_near(kid) is True, "a bus inside the zone was not near")
    with states(outside):
        check(bus.bus_is_near(kid) is False, "a bus 5km out was inside the zone")
    # No radius on the zone is a PIN, not a fence — fall through to the typed
    # metres rather than silently never firing.
    pin = {'state': 'zoning',
           'attributes': {'latitude': 35.0, 'longitude': -78.0, 'radius': 0}}

    def pin_states(entity_id):
        return pin if entity_id.startswith('zone.') else inside

    with mock.patch('services.ha_api.get_state', side_effect=pin_states),             mock.patch.object(bus, '_home_coords', return_value=(35.0, -78.0)):
        check(bus.bus_is_near(kid) is False,
              "a radiusless zone fired with no fallback radius set")
        check(bus.bus_is_near({**kid, 'bus_near_radius_m': 500}) is True,
              "a radiusless zone did not fall through to metres from home")



def scenario_each_child_points_at_their_own_stop():
    """Two kids at different schools have different stops, so every bus field
    is a MEMBER field — and the stop pin falls back to the "nearly here" zone,
    because in most houses they are the same circle and asking twice means
    asking somebody to keep two fields in agreement forever."""
    from models import schemas
    for field in ('bus_stop_entity', 'bus_near_zone'):
        check(field in schemas.FamilyMember.model_fields,
              f"{field} is not per-member, so siblings would share a stop")
    seen = {}

    def get(entity_id):
        seen['id'] = entity_id
        return {'state': 'zoning',
                'attributes': {'latitude': 35.0, 'longitude': -78.0, 'radius': 300}}

    with mock.patch('services.ha_api.get_state', side_effect=get):
        got = bus.stop_position({**KID, 'bus_near_zone': 'zone.addison_stop'})
        check(got == (35.0, -78.0) and seen['id'] == 'zone.addison_stop',
              f"the fence zone was not reused as the stop pin: {seen}")
        bus.stop_position({**KID, 'bus_near_zone': 'zone.a',
                           'bus_stop_entity': 'zone.b'})
        check(seen['id'] == 'zone.b',
              f"an explicit stop lost to the fence zone: {seen['id']}")



def scenario_siblings_share_one_bus():
    """Two kids on one bus is one vehicle, one pin and one sentence. HCTB
    gives each STUDENT their own tracker entity, so keyed by entity the wall
    would stack two identical pins and the kitchen would say the same thing
    twice — which is the failure this exists to prevent."""
    a = {**KID, "id": "a", "name": "Addison Smith"}
    b = {**KID, "id": "b", "name": "Cole Smith"}
    # Same bus number: the honest key when the platform publishes one.
    with mock.patch.object(bus, 'bus_number', return_value='42'):
        check(bus.bus_key(a) == bus.bus_key(b),
              "siblings on bus 42 were treated as two buses")
    # No number: same coordinates is the same vehicle.
    same = {'state': 'x', 'attributes': {'latitude': 35.12345, 'longitude': -78.5}}
    with mock.patch.object(bus, 'bus_number', return_value=None),             mock.patch('services.ha_api.get_state', return_value=same):
        check(bus.bus_key(a) == bus.bus_key(b),
              "two trackers at one point were treated as two buses")
    # Different buses must never merge.
    with mock.patch.object(bus, 'bus_number', side_effect=['42', '17']):
        check(bus.bus_key(a) != bus.bus_key(b), "two real buses were merged")


def scenario_one_bus_says_one_sentence_naming_everyone():
    """The push is per child — it goes to their own phone. The spoken form is
    for a room, so it names everyone it is for."""
    kids = [{**KID, "name": "Addison Smith"}, {**KID, "name": "Cole Smith"}]
    title, body, spoken = bus.route_start_message(kids)
    check('Addison and Cole' in spoken, f"the room is not told who: {spoken}")
    check('Addison' not in body, f"the push names them in the third person: {body}")
    three = kids + [{**KID, "name": "Rey Smith"}]
    check('Addison, Cole and Rey' in bus.near_message(three)[2],
          "three names are not listed like a person would say them")



def scenario_the_bus_is_out_sensor_is_found_not_assumed():
    """Reported from a real house: their trigger is `sensor.{first}_ignition_on`
    — a different DOMAIN and a different shape from the pair we composed. That
    is not a cosmetic miss. `bus_active` gates the live estimate, the chip, the
    route-start event and "nearly here", so probing only our own guess left the
    entire live layer switched off, and NOTHING said so: a bus that is never
    out and a bus we cannot see produce the same silence."""
    bus._active_entity_cache.clear()

    def only(entity_id, state='on'):
        def get(eid):
            return {'state': state} if eid == entity_id else None
        return mock.patch('services.ha_api.get_state', side_effect=get)

    for ent in ('binary_sensor.addison_bus_ignition_on',   # the confirmed one
                'sensor.addison_bus_ignition_on',
                'sensor.addison_ignition_on',
                'binary_sensor.addison_bus_in_service'):
        bus._active_entity_cache.clear()
        with only(ent):
            check(bus.bus_active(dict(KID)) is True,
                  f"the bus-is-out sensor was not found as {ent}")
    # Off is off, whichever name it wears.
    bus._active_entity_cache.clear()
    with only('binary_sensor.addison_bus_ignition_on', state='off'):
        check(bus.bus_active(dict(KID)) is False, "an off sensor read as out")
    # An explicit override still wins outright.
    bus._active_entity_cache.clear()
    with only('binary_sensor.somewhere_else'):
        check(bus.bus_active({**KID, 'bus_active_entity': 'binary_sensor.somewhere_else'})
              is True, "an explicit bus-is-out entity was ignored")
    # Nothing at all is False, not an exception.
    bus._active_entity_cache.clear()
    with mock.patch('services.ha_api.get_state', return_value=None):
        check(bus.bus_active(dict(KID)) is False, "no entity did not resolve to False")


def scenario_a_live_tracker_is_a_running_bus_when_nothing_says_otherwise():
    """Reported from the household: correct tracker, correct stop zone, and
    no pin ever. Every discovery candidate above is shaped like HCTB's, so a
    house tracking its bus by any other integration got `active_entity` None
    and `bus_active` False forever — the exact silent-whole-feature-off
    failure the candidate list's own comment warns about, one level up.

    A device_tracker that reported ninety seconds ago IS a bus that is
    running. The freshness window keeps the reason this was ever a gate: no
    stale pin claiming a bus that went home hours ago."""
    import datetime as _dt
    bus._active_entity_cache.clear()
    now = _dt.datetime.now(_dt.timezone.utc)
    kid = {**KID, 'bus_tracker_entity': 'device_tracker.first_student_bus'}

    def tracker(ago_secs, lat=35.7, lon=-78.7):
        stamp = (now - _dt.timedelta(seconds=ago_secs)).isoformat()
        def get(eid):
            if eid == 'device_tracker.first_student_bus':
                return {'state': 'not_home', 'last_updated': stamp,
                        'attributes': {'latitude': lat, 'longitude': lon}}
            return None            # nothing HCTB-shaped exists on this house
        return mock.patch('services.ha_api.get_state', side_effect=get)

    with tracker(90):
        check(bus.bus_active(kid) is True,
              "a tracker reporting 90 seconds ago did not read as a bus that "
              "is out — the whole live layer stays off for any non-HCTB house")
    with tracker(6 * 3600):
        check(bus.bus_active(kid) is False,
              "a six-hour-old fix read as a running bus — that is the stale "
              "pin this gate exists to prevent")

    # An in-service entity that EXISTS still wins outright, including off.
    bus._active_entity_cache.clear()
    def with_sensor(eid):
        if eid == 'binary_sensor.addison_bus_ignition_on':
            return {'state': 'off'}
        if eid == 'device_tracker.first_student_bus':
            return {'state': 'not_home', 'last_updated': now.isoformat(),
                    'attributes': {'latitude': 35.7, 'longitude': -78.7}}
        return None
    with mock.patch('services.ha_api.get_state', side_effect=with_sensor):
        check(bus.bus_active(kid) is False,
              "a fresh tracker overrode an in-service sensor that says off — "
              "an entity that exists is authoritative")


def scenario_the_bus_says_which_gate_it_failed():
    """Every gate here fails silently and they all look identical from a
    wall. The diagnosis is the difference between reading that and guessing:
    it names the tracker it looked for, whether that entity exists, whether
    it carries coordinates, how long ago it reported, the in-service entity
    and its state — and the card option that is off by default."""
    bus._active_entity_cache.clear()
    with mock.patch('services.ha_api.get_state', return_value=None):
        d = bus.bus_diagnosis({**KID, 'bus_tracker_entity': 'device_tracker.nope'})
    check(d['tracker_entity'] == 'device_tracker.nope'
          and d['tracker_exists'] is False and d['tracker_has_coords'] is False,
          f"the diagnosis must name what it looked for and what it found: {d}")
    check(d['active'] is False and d['active_entity'] is None,
          f"and say the bus is not reading as out: {d}")
    check('Show school buses' in d['note'],
          "the diagnosis must mention the card option that is off by "
          "default — it is the likeliest miss and no entity reveals it")


SCENARIOS = [
    scenario_a_live_tracker_is_a_running_bus_when_nothing_says_otherwise,
    scenario_the_bus_says_which_gate_it_failed,
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
    scenario_the_autodiscovered_names_are_the_ones_hctb_publishes,
    scenario_the_stop_time_is_required_even_with_a_live_tracker,
    scenario_the_stop_is_never_guessed,
    scenario_near_home_needs_a_radius_and_two_ends,
    scenario_the_events_have_something_to_say_out_loud,
    scenario_speaking_is_opt_in_per_child,
    scenario_every_b3_field_has_a_hand_path,
    scenario_a_zone_is_already_a_geofence,
    scenario_each_child_points_at_their_own_stop,
    scenario_siblings_share_one_bus,
    scenario_one_bus_says_one_sentence_naming_everyone,
    scenario_the_bus_is_out_sensor_is_found_not_assumed,
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
