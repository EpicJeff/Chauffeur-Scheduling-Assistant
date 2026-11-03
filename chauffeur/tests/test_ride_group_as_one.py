"""Ride groups with a mode: one drop-off, one pick-up (2026-11-03).

Spec: docs/superpowers/specs/2026-11-03-ride-group-as-one-design.md.

Back-to-back events at one place, grouped. Set the group to "one drop-off,
one pick-up" and the refresh makes ONE drop-off leg at the first start and
ONE pick-up leg at the last end, hung off the first member; the inner and
last members get no drive of their own. Same place only; a day-of "staying
after all" on any member cancels the merge for that day; per occurrence,
never a rule.

Run from chauffeur/:  python tests/test_ride_group_as_one.py
"""
import datetime
import os

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR, mocks maps)

from fastapi import HTTPException

from models.schemas import Event
from services import ride_groups, storage

DAY = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) \
    + datetime.timedelta(days=1)
TODAY = datetime.date.today()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mk_event(eid, cal, start_h, start_m=0, mins=60, loc="Pool", day=DAY, title=None):
    start = day.replace(hour=start_h, minute=start_m)
    return Event(id=eid, title=title or f"Event {eid}", start=start,
                 end=start + datetime.timedelta(minutes=mins), location=loc,
                 calendar_ids=[cal], source_event_ids=[f"cal::{eid}"])


def _reset():
    storage.ride_groups_table.truncate()
    storage.app_state_table.truncate()


def _cache(*events):
    storage.cache_table.truncate()
    storage.set_cached_schedule({
        "events": [e.model_dump(mode="json") for e in events],
        "assignments": {}, "unassigned": []})


def _group(events, mode=None):
    return ride_groups.group([(e.model_dump(mode="json"), e.id) for e in events], mode=mode)


def _stamped(*events):
    ride_groups.stamp_ride_groups(list(events))
    return events


def _ids(got):
    return [e['id'] if isinstance(e, dict) else e.id for e in got.get('events', [])]


def _hm(iso):
    return str(iso)[11:16]


# --- 1. the store carries the mode -------------------------------------------

def scenario_the_store_carries_the_mode():
    _reset()
    swim, dive = mk_event("swim", "cal_a", 9), mk_event("dive", "cal_b", 10)
    gid = _group([swim, dive], mode='one')
    rows = storage.get_ride_group_rows()
    check(len(rows) == 2 and all(r.get('mode') == 'one' and r['group_id'] == gid for r in rows),
          f"mode 'one' on every row: {rows}")
    _stamped(swim, dive)
    check(ride_groups.group_mode_of(swim) == 'one' and ride_groups.group_mode_of(dive) == 'one'
          and swim.ride_group_mode == 'one', f"stamped: {swim.ride_group_mode} {dive.ride_group_mode}")
    # Grouping the same members again with no mode keeps it.
    _group([swim, dive])
    check(all(r.get('mode') == 'one' for r in storage.get_ride_group_rows()), "no mode given keeps 'one'")
    # A third member joins as 'one'.
    kick = mk_event("kick", "cal_a", 11)
    _group([kick, dive])
    rows = storage.get_ride_group_rows()
    check(len(rows) == 3 and all(r.get('mode') == 'one' and r['group_id'] == gid for r in rows),
          f"a joiner takes the group's mode: {rows}")
    # Back to ride together.
    _group([swim, dive, kick], mode='ride')
    check(all((r.get('mode') or 'ride') == 'ride' for r in storage.get_ride_group_rows()), "mode 'ride' clears it")
    _stamped(swim, dive, kick)
    check(ride_groups.group_mode_of(swim) == 'ride' and not swim.ride_group_mode, f"{swim.ride_group_mode}")
    # A plain new group is 'ride'.
    _reset()
    _group([swim, dive])
    check(all((r.get('mode') or 'ride') == 'ride' for r in storage.get_ride_group_rows()), "a new group is 'ride'")


def scenario_one_needs_the_same_place_and_means_whole_events():
    _reset()
    swim, rink = mk_event("swim", "cal_a", 9), mk_event("dive", "cal_b", 10, loc="Rink")
    try:
        _group([swim, rink], mode='one')
        check(False, "different places must refuse")
    except ValueError as err:
        check("same place" in str(err), f"the words: {err}")
    check(storage.get_ride_group_rows() == [], "nothing written on refusal")
    nowhere = mk_event("dive", "cal_b", 10, loc="")
    try:
        _group([swim, nowhere], mode='one')
        check(False, "an empty place must refuse")
    except ValueError:
        pass
    # Case and spacing are not a different place.
    pool2 = mk_event("dive", "cal_b", 10, loc=" pool ")
    _group([swim, pool2], mode='one')
    check(len(storage.get_ride_group_rows()) == 2, "normalised places match")
    # A leg id under mode 'one' means its parent: the row is leg ''.
    _reset()
    camp = mk_event("camp", "cal_a", 9, mins=360)
    dive = mk_event("dive", "cal_b", 10)
    drop = camp.model_dump(mode="json")
    drop.update(id="camp_dropoff", original_start=camp.start.isoformat())
    ride_groups.group([(drop, "camp_dropoff"), (dive.model_dump(mode="json"), "dive")], mode='one')
    rows = storage.get_ride_group_rows()
    check(all((r.get('leg') or '') == '' for r in rows), f"whole-event rows only: {rows}")
    _stamped(camp, dive)
    check(camp.ride_groups.get('') and camp.ride_group_mode == 'one', f"{camp.ride_groups} {camp.ride_group_mode}")
    check(ride_groups.ungroup(drop, "camp_dropoff") and storage.get_ride_group_rows() == [],
          "ungrouping by the leg id takes the parent out and the pair dissolves")


# --- 2. the merge plan ---------------------------------------------------------

def _plan(events, overrides=None):
    _stamped(*events)
    return ride_groups.merge_as_one(list(events), overrides or {})


def scenario_two_members_become_one_dropoff_and_one_pickup():
    _reset()
    swim = mk_event("swim", "cal_a", 9, title="Swim")
    dive = mk_event("dive", "cal_b", 10, title="Dive")
    _group([swim, dive], mode='one')
    plan = _plan([swim, dive])
    check(set(plan['skip']) == {'swim', 'dive'} and set(plan['legs']) == {'swim'}, f"{plan}")
    drop, pick = plan['legs']['swim']
    check(drop.id == 'swim_dropoff' and drop.event_type == 'dropoff' and drop.start == swim.start and drop.end == swim.start,
          f"the drop-off at the first start: {drop.id} {drop.start} {drop.end}")
    check(pick.id == 'swim_pickup' and pick.event_type == 'pickup' and pick.start == dive.end and pick.end == dive.end,
          f"the pick-up at the last end: {pick.id} {pick.start} {pick.end}")
    check(drop.original_start == swim.start and drop.original_end == dive.end
          and pick.original_start == swim.start and pick.original_end == dive.end
          and drop.original_event_id == 'swim' and pick.original_event_id == 'swim',
          f"both carry the block's span and the first's id: {drop.original_start} {drop.original_end}")
    check(drop.title == 'Dropoff: Swim + Dive' and pick.title == 'Pickup: Swim + Dive', f"{drop.title} / {pick.title}")
    check(drop.calendar_ids == ['cal_a', 'cal_b'] and pick.calendar_ids == ['cal_a', 'cal_b']
          and drop.source_event_ids == ['cal::swim', 'cal::dive'],
          f"calendars and sources are the union in start order: {drop.calendar_ids} {drop.source_event_ids}")
    check(drop.needs_triage is False and pick.needs_triage is False, "legs never need triage")
    check(drop.ride_groups == swim.ride_groups and drop.ride_group_mode == 'one', "the legs carry the stamp")


def scenario_gaps_three_members_and_order_do_not_matter():
    _reset()
    a = mk_event("a", "cal_a", 9, title="Swim")
    b = mk_event("b", "cal_b", 10, 30, title="Dive")      # a 30-min gap: the kids wait
    c = mk_event("c", "cal_a", 11, 30, mins=90, title="Swim")  # same title as a: deduped
    _group([a, b, c], mode='one')
    plan = _plan([c, a, b])   # any order in
    check(set(plan['legs']) == {'a'} and set(plan['skip']) == {'a', 'b', 'c'}, f"{plan}")
    drop, pick = plan['legs']['a']
    check(drop.start == a.start and pick.start == c.end and pick.original_end == c.end, f"{drop.start} {pick.start}")
    check(drop.title == 'Dropoff: Swim + Dive' and drop.calendar_ids == ['cal_a', 'cal_b'], f"{drop.title} {drop.calendar_ids}")


def scenario_no_merge_when_it_is_not_a_block():
    _reset()
    swim, dive = mk_event("swim", "cal_a", 9), mk_event("dive", "cal_b", 10)
    # A 'ride' group is no merge.
    _group([swim, dive])
    check(_plan([swim, dive]) == {'legs': {}, 'skip': set()}, "a ride group merges nothing")
    # A member alone on the day is no merge.
    _reset()
    _group([swim, dive], mode='one')
    check(_plan([swim]) == {'legs': {}, 'skip': set()}, "one member is no merge")
    # A day-of 'stay' on any member cancels the merge for that day.
    plan = _plan([swim, dive], {'dive': {'action': 'stay'}})
    check(plan == {'legs': {}, 'skip': set()}, f"a stay override on the second member cancels the merge: {plan}")
    plan = _plan([swim, dive], {'swim': {'action': 'split'}})
    check(set(plan['legs']) == {'swim'}, "a split override changes nothing")
    # Places that drifted apart since the group was written: no merge.
    moved = mk_event("dive", "cal_b", 10, loc="Rink")
    check(_plan([swim, moved]) == {'legs': {}, 'skip': set()}, "different places merge nothing")
    # A background trip never counts.
    bg = mk_event("bg", "cal_a", 12)
    bg.event_type = 'background_trip'
    _group([swim, dive, bg], mode='one')
    plan = _plan([swim, dive, bg])
    check(set(plan['skip']) == {'swim', 'dive'} and 'bg' not in plan['skip'], f"{plan}")


# --- 3. the refresh runs it ----------------------------------------------------

def _solve_two(mode, hours=(2, 2), place2='9 Rec Center Rd', overrides=None):
    import main
    from services import calendar as cal_svc
    for t in ('drivers_table', 'passengers_table', 'members_table',
              'daily_schedules_table', 'custom_schedules_table',
              'settings_table', 'event_configs_table', 'rules_table',
              'overrides_table', 'ride_groups_table', 'app_state_table', 'cache_table'):
        tbl = getattr(storage, t, None)
        if tbl is not None:
            tbl.truncate()
    storage.settings_table.insert({'calendar_ids': ['cal_house'], 'days_to_build': 1,
                                   'home_location': '1 Home St'})
    storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#3b82f6', 'group': 'primary',
                        'priority_index': 1, 'calendar_ids': [], 'home_location': '1 Home St'})
    storage.add_passenger({'id': 'p1', 'name': 'Lily', 'calendar_ids': ['cal_lily'], 'hashtags': []})
    storage.add_member({'id': 'm1', 'name': 'Lily', 'role': 'child', 'passenger_id': 'p1'})
    # Configured, so neither waits in the inbox (an untriaged event is never solved).
    storage.event_configs_table.insert({'google_id': 'gev1', 'passenger_ids': ['p1']})
    storage.event_configs_table.insert({'google_id': 'gev2', 'passenger_ids': ['p1']})
    at = lambda h: datetime.datetime.combine(TODAY, datetime.time(h, 0))  # noqa: E731
    protos = [dict(id='gev1', title='Swim', start=at(16), end=at(16 + hours[0]), location='9 Rec Center Rd',
                   description='', calendar_ids=['cal_lily'], source_event_ids=['gev1']),
              dict(id='gev2', title='Dive', start=at(16 + hours[0]), end=at(16 + hours[0] + hours[1]), location=place2,
                   description='', calendar_ids=['cal_lily'], source_event_ids=['gev2'])]
    evs = [Event(**p) for p in protos]
    if mode:
        ride_groups.group([(e.model_dump(mode='json'), e.id) for e in evs], mode=mode)
    for eid, action in (overrides or {}).items():
        storage.set_attendance_override(eid, action)
    real = cal_svc.fetch_upcoming_events
    try:
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**p) for p in protos]
        res = main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(), force_refresh=True)
    finally:
        cal_svc.fetch_upcoming_events = real
    check(not res.get('error'), "the day did not solve: %s" % res.get('error'))
    return res


def scenario_the_refresh_makes_one_dropoff_and_one_pickup():
    got = _solve_two('one')
    ids = _ids(got)
    check('gev1_dropoff' in ids and 'gev1_pickup' in ids, f"the block's two legs exist: {ids}")
    check('gev2_dropoff' not in ids and 'gev2_pickup' not in ids, f"the second member has no legs: {ids}")
    legs = {e['id']: e for e in got['events'] if e['id'] in ('gev1_dropoff', 'gev1_pickup')}
    check(_hm(legs['gev1_dropoff']['start']) == '16:00' and _hm(legs['gev1_pickup']['start']) == '20:00'
          and _hm(legs['gev1_pickup']['original_end']) == '20:00',
          f"drop-off at the first start, pick-up at the last end: {legs['gev1_dropoff']['start']} {legs['gev1_pickup']['start']}")
    check(legs['gev1_pickup']['title'] == 'Pickup: Swim + Dive', legs['gev1_pickup']['title'])
    asg = got.get('assignments', {})
    check(asg.get('gev1_dropoff') == 'd1' and asg.get('gev1_pickup') == 'd1', f"both legs are driven: {asg}")
    check('gev2' not in asg and 'gev1' not in asg, f"no whole member is assigned: {asg}")
    check('gev2' in ids and 'gev1' in ids, "the members stay in the page data, as a split parent does")


def scenario_the_refresh_leaves_a_ride_group_and_an_overridden_day_alone():
    got = _solve_two('ride')
    ids = _ids(got)
    check(all(x in ids for x in ('gev1_dropoff', 'gev1_pickup', 'gev2_dropoff', 'gev2_pickup')),
          f"a ride group still splits each two-hour member: {ids}")
    got = _solve_two('one', overrides={'gev2': 'stay'})
    ids = _ids(got)
    check('gev2_dropoff' not in ids and 'gev1_dropoff' in ids and 'gev1_pickup' in ids
          and _hm(next(e for e in got['events'] if e['id'] == 'gev1_pickup')['start']) == '18:00',
          f"a stay on the second member: each decides alone, the first's pick-up is at its own end: {ids}")
    got = _solve_two(None)
    check('gev1_dropoff' in _ids(got) and 'gev2_dropoff' in _ids(got), "ungrouped is the shipped answer")


# --- 4. routes and the agent ---------------------------------------------------

def scenario_the_routes_and_the_agent_take_the_mode():
    import main
    from services import agent_tools_v2
    _reset()
    main.trigger_background_refresh = lambda *a, **k: None
    swim, dive = mk_event("swim", "cal_a", 9), mk_event("dive", "cal_b", 10)
    _cache(swim, dive)
    res = main.ride_group_api({"event_ids": ["swim", "dive"], "mode": "one"}, request=None)
    rows = storage.get_ride_group_rows()
    check(res.get("status") == "grouped" and len(rows) == 2 and all(r.get('mode') == 'one' for r in rows),
          f"POST with mode 'one': {res} {rows}")
    res = main.ride_group_api({"event_ids": ["swim", "dive"], "mode": "ride"}, request=None)
    check(all((r.get('mode') or 'ride') == 'ride' for r in storage.get_ride_group_rows()), "POST with mode 'ride' switches back")
    rink = mk_event("dive", "cal_b", 10, loc="Rink")
    _cache(swim, rink)
    _reset()
    try:
        main.ride_group_api({"event_ids": ["swim", "dive"], "mode": "one"}, request=None)
        check(False, "different places must be a 400")
    except HTTPException as e:
        check(e.status_code == 400 and "same place" in str(e.detail), f"{e.status_code} {e.detail}")
    # DELETE on a merged leg id ungroups the parent.
    _cache(swim, dive)
    main.ride_group_api({"event_ids": ["swim", "dive"], "mode": "one"}, request=None)
    res = main.ride_ungroup_api("swim_dropoff", {}, request=None)
    check(res.get("status") == "ungrouped" and storage.get_ride_group_rows() == [], f"{res} {storage.get_ride_group_rows()}")
    # The agent.
    _cache(swim, dive)
    day = DAY.date().isoformat()
    res = agent_tools_v2.TOOL_HANDLERS["group_events_ride_together"](
        {"event_names": ["swim", "dive"], "target_date": day, "as_one": True})
    rows = storage.get_ride_group_rows()
    check(res.get("status") == "success" and len(rows) == 2 and all(r.get('mode') == 'one' for r in rows),
          f"Argyle groups as one: {res} {rows}")
    check('as one event' in res.get('message', '') and '09:00' in res['message'] and '11:00' in res['message'],
          f"and says the drop-off and pick-up times: {res.get('message')}")
    schema = next(t for t in agent_tools_v2.get_available_tools() if t.get('name') == 'group_events_ride_together')
    props = (schema.get('input_schema') or schema.get('parameters') or {}).get('properties', {})
    check('as_one' in props, f"the tool exposes as_one: {list(props)}")


# --- 5. the hand path ----------------------------------------------------------

def scenario_the_hand_path_exists():
    dash = open(os.path.join(ROOT, 'templates', 'dashboard.html'), encoding='utf-8').read()
    check("'One drop-off, one pick-up'" in dash and "group_one" in dash,
          "the drop dialog offers one drop-off, one pick-up")
    check("Everyone waits at the venue" in dash, "the dialog says what it means for the kids")
    check("'Ride together only'" in dash, "the chip switches a merged group back")
    timeline = open(os.path.join(ROOT, 'templates', 'components', 'schedule_timeline.html'), encoding='utf-8').read()
    check("ride_group_mode" in timeline, "merged legs wear the chip")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} ride-group-as-one scenarios passed")
