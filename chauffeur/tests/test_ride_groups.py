"""Ride groups -- drop one event onto another and they ride together.

Two kids, two events at the same place a little apart. On paper one driver
can't cover both (no time to go home for the second kid); in life both kids
get in the car at the start. Load-bearing properties:

  1. **A grouped pair is no conflict.** The solver gives both to one driver
     where, ungrouped, it had to drop one.
  2. **Never split.** With two drivers free, a group still goes to one.
  3. **These occurrences only.** Rows live in their own table keyed
     (instance google id, date, leg) -- never a rule, never the event config.
     A sibling occurrence on another day is untouched.
  4. **No limit, and groups merge.** Dropping onto a grouped event joins its
     group; ungrouping down to one member dissolves the group.
  5. **Same day only**, refused out loud.
  6. **The diagnostics suggest it** when it is a sensible day (close by,
     different kids, a bearable wait) and not otherwise.
  7. **Grouping re-solves**: it rides the events hash.
  8. **The hand path exists**: drop-onto-event with a Group / Assign choice,
     the 🔗 chip to ungroup, the diagnostics button.

Run from chauffeur/:  python tests/test_ride_groups.py
"""
import datetime
import os

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR, mocks maps)

from fastapi import HTTPException

from models.schemas import Driver, Event, Passenger
from services import ride_groups, storage
from solver import matcher

DAY = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) \
    + datetime.timedelta(days=1)

PAX = [Passenger(id="pa", name="Ava", calendar_ids=["cal_a"]),
       Passenger(id="pb", name="Ben", calendar_ids=["cal_b"])]


def mk_driver(i):
    return Driver(id=f"d{i}", name=f"Driver {i}", color_code="#fff",
                  group="primary", priority_index=1)


def mk_event(eid, cal, start_h, start_m, mins=60, loc="Pool", day=DAY):
    start = day.replace(hour=start_h, minute=start_m)
    return Event(id=eid, title=f"Event {eid}", start=start,
                 end=start + datetime.timedelta(minutes=mins), location=loc,
                 calendar_ids=[cal], source_event_ids=[f"cal::{eid}"])


def pair():
    # Ava 9:00-10:00 at the pool, Ben 9:05-10:05 at the rink next door (the
    # harness mock puts any two places ten minutes apart). Ungrouped, one
    # driver can't drop Ava and be at the rink by 9:05.
    return mk_event("swim", "cal_a", 9, 0), mk_event("dive", "cal_b", 9, 5, loc="Rink")


def _reset():
    storage.ride_groups_table.truncate()


def _cache(*events):
    storage.cache_table.truncate()
    storage.set_cached_schedule({
        "events": [e.model_dump(mode="json") for e in events],
        "assignments": {}, "unassigned": []})


def _stamped(*events):
    ride_groups.stamp_ride_groups(list(events))
    return events


def scenario_ungrouped_the_pair_is_a_conflict():
    _reset()
    a, b = pair()
    assignments, unassigned, _, _ = matcher.solve_schedule(
        [a, b], [mk_driver(1)], [], passengers=PAX)
    check(len(unassigned) == 1,
          f"the setup must be a real conflict for one driver: {assignments} / {unassigned}")


def scenario_grouped_one_driver_covers_both():
    _reset()
    a, b = pair()
    _cache(a, b)
    ride_groups.group([(a.model_dump(mode="json"), a.id), (b.model_dump(mode="json"), b.id)])
    _stamped(a, b)
    check(a.ride_groups.get('') and a.ride_groups == b.ride_groups,
          f"both carry one group after the stamp: {a.ride_groups} / {b.ride_groups}")
    assignments, unassigned, _, _ = matcher.solve_schedule(
        [a, b], [mk_driver(1)], [], passengers=PAX)
    check(not unassigned and assignments == {"swim": "d1", "dive": "d1"},
          f"riding together, one driver does both: {assignments} / {unassigned}")


def scenario_a_group_is_never_split():
    _reset()
    a, b = pair()
    ride_groups.group([(a.model_dump(mode="json"), a.id), (b.model_dump(mode="json"), b.id)])
    _stamped(a, b)
    assignments, unassigned, _, _ = matcher.solve_schedule(
        [a, b], [mk_driver(1), mk_driver(2)], [], passengers=PAX)
    check(not unassigned and assignments["swim"] == assignments["dive"],
          f"two drivers free, still one car: {assignments}")


def scenario_the_route_stops_sending_the_driver_home():
    # The user's case: same place, back to back. The solver already lets one
    # driver chain them, but the route sent that driver HOME for Ben between
    # the two and showed him late. Grouped, Ben is already in the car.
    _reset()
    a = mk_event("swim", "cal_a", 9, 0)
    b = mk_event("dive", "cal_b", 10, 5)
    asg = {"swim": "d1", "dive": "d1"}
    edges, _, _ = matcher.compute_route_edges(asg, [a, b], [mk_driver(1)],
                                              home_location="Home", passengers=PAX)
    before = edges["d1"]["swim"]
    check(before.get("pickup_waypoint") and before["travel_mins"] > 0,
          f"ungrouped, the driver goes home for Ben: {before}")
    check((before.get("ride_together") or {}).get("event_id") == "swim"
          and before["ride_together"]["late_mins"] == before["late_mins"] > 0,
          f"and the late leg offers riding together: {before}")
    ride_groups.group([(a.model_dump(mode="json"), a.id), (b.model_dump(mode="json"), b.id)])
    _stamped(a, b)
    edges, _, _ = matcher.compute_route_edges(asg, [a, b], [mk_driver(1)],
                                              home_location="Home", passengers=PAX)
    after = edges["d1"]["swim"]
    check(not after.get("pickup_waypoint") and after["travel_mins"] == 0
          and not after.get("late_mins") and not after.get("ride_together"),
          f"grouped, no trip home and nobody late: {after}")


def scenario_routing_treats_the_group_as_one_trip():
    _reset()
    a, b = pair()
    ride_groups.group([(a.model_dump(mode="json"), a.id), (b.model_dump(mode="json"), b.id)])
    _stamped(a, b)
    pairs = matcher.get_grouped_event_pairs([a, b], [], PAX)
    check(("swim", "dive") in pairs and ("dive", "swim") in pairs,
          f"the grouped pair reaches the router's pair set: {pairs}")


def scenario_only_these_occurrences():
    _reset()
    a, b = pair()
    ride_groups.group([(a.model_dump(mode="json"), a.id), (b.model_dump(mode="json"), b.id)])
    nxt = DAY + datetime.timedelta(days=7)
    a2 = mk_event("swim", "cal_a", 9, 0, day=nxt)
    a2.source_event_ids = ["cal::swim"]  # same google id, next week's date
    b2 = mk_event("dive", "cal_b", 9, 5, day=nxt)
    _stamped(a2, b2)
    check(not a2.ride_groups and not b2.ride_groups,
          "next week's occurrences are untouched -- a ride group is not a rule")
    check(not storage.get_rules() if hasattr(storage, 'get_rules') else True,
          "and no rule was written")
    check(all('ride_group' not in (storage.get_event_config(g) or {}) for g in ('swim', 'dive')),
          "and nothing landed in the event config")


def scenario_groups_grow_merge_and_dissolve():
    _reset()
    a, b = pair()
    c = mk_event("art", "cal_a", 11, 0)
    d = mk_event("chess", "cal_b", 11, 0)
    j = lambda e: e.model_dump(mode="json")
    g1 = ride_groups.group([(j(a), a.id), (j(b), b.id)])
    g2 = ride_groups.group([(j(c), c.id), (j(d), d.id)])
    check(g1 != g2, "two separate groups")
    # Drop c onto b: c joins b's group, and c's old group comes along.
    g = ride_groups.group([(j(c), c.id), (j(b), b.id)])
    check(g == g1, "the drop target's group is kept")
    _stamped(a, b, c, d)
    check(len({e.ride_groups.get('') for e in (a, b, c, d)}) == 1,
          f"all four ride together now -- no limit, groups merge: {[e.ride_groups for e in (a, b, c, d)]}")
    for e in (a, b, c):
        ride_groups.ungroup(j(e), e.id)
    rows = storage.get_ride_group_rows()
    check(rows == [], f"ungrouping down to one member dissolves the group: {rows}")


def scenario_legs_group_independently():
    _reset()
    camp = mk_event("camp", "cal_a", 9, 0, mins=360)
    dive = mk_event("dive", "cal_b", 9, 5)
    drop = camp.model_dump(mode="json")
    drop.update(id="camp_dropoff", original_start=camp.start.isoformat())
    ride_groups.group([(drop, "camp_dropoff"), (dive.model_dump(mode="json"), "dive")])
    _stamped(camp, dive)
    check(camp.ride_groups == {'dropoff': dive.ride_groups['']},
          f"only the dropoff leg is grouped: {camp.ride_groups}")
    leg_drop = camp.model_copy(update={"id": "camp_dropoff"})
    leg_pick = camp.model_copy(update={"id": "camp_pickup"})
    check(ride_groups.same_group(leg_drop, dive) and not ride_groups.same_group(leg_pick, dive),
          "the pickup leg stays free")


def scenario_same_day_only():
    _reset()
    a, _ = pair()
    other = mk_event("dive", "cal_b", 9, 5, day=DAY + datetime.timedelta(days=1))
    try:
        ride_groups.group([(a.model_dump(mode="json"), a.id), (other.model_dump(mode="json"), other.id)])
        check(False, "grouping across days must be refused")
    except ValueError as e:
        check("same day" in str(e), f"refused out loud: {e}")


def scenario_the_diagnostics_suggest_riding_together():
    _reset()
    a, b = pair()
    diag = matcher.compute_diagnostics(["dive"], [a, b], [mk_driver(1)], {},
                                       {"swim": "d1"}, [], [], passengers=PAX)
    reason = diag["dive"]["d1"]
    rt = reason.get("ride_together")
    check(reason["type"] == "conflict" and rt and rt["event_id"] == "swim",
          f"the conflict offers riding together: {reason}")
    check(rt["wait_mins"] == 5 and rt["waiting_name"] in ("Ava", "Ben"),
          f"and says who waits how long: {rt}")


def scenario_no_suggestion_when_it_is_not_a_sensible_day():
    _reset()
    a = mk_event("swim", "cal_a", 9, 0)
    far = mk_event("dive", "cal_b", 9, 5, loc="Rink")  # mock: 10 min apart -> still ok
    far_wait = mk_event("dive", "cal_b", 9, 5, mins=180)  # Ava waits 2h05 after
    same_kid = mk_event("dive", "cal_a", 9, 5)
    for b, why in ((far_wait, "a two-hour wait"), (same_kid, "the same kid")):
        diag = matcher.compute_diagnostics(["dive"], [a, b], [mk_driver(1)], {},
                                           {"swim": "d1"}, [], [], passengers=PAX)
        reason = diag["dive"]["d1"]
        check(not reason.get("ride_together"), f"no offer for {why}: {reason}")
    diag = matcher.compute_diagnostics(["dive"], [a, far], [mk_driver(1)], {},
                                       {"swim": "d1"}, [], [], passengers=PAX)
    check(diag["dive"]["d1"].get("ride_together"),
          "ten minutes apart is still close enough to offer")
    old = matcher.RIDE_TOGETHER_MAX_TRAVEL_MINS
    matcher.RIDE_TOGETHER_MAX_TRAVEL_MINS = 5
    try:
        diag = matcher.compute_diagnostics(["dive"], [a, far], [mk_driver(1)], {},
                                           {"swim": "d1"}, [], [], passengers=PAX)
        check(not diag["dive"]["d1"].get("ride_together"), "too far apart: no offer")
    finally:
        matcher.RIDE_TOGETHER_MAX_TRAVEL_MINS = old


def scenario_grouped_events_are_not_diagnosed_as_conflicts():
    _reset()
    a, b = pair()
    ride_groups.group([(a.model_dump(mode="json"), a.id), (b.model_dump(mode="json"), b.id)])
    _stamped(a, b)
    diag = matcher.compute_diagnostics(["dive"], [a, b], [mk_driver(1)], {},
                                       {"swim": "d1"}, [], [], passengers=PAX)
    check(diag["dive"]["d1"]["type"] != "conflict",
          f"a grouped partner is never named as the conflict: {diag}")


def scenario_grouping_rides_the_events_hash():
    import main
    _reset()
    a, b = pair()
    before = main.hash_events([a, b])
    ride_groups.group([(a.model_dump(mode="json"), a.id), (b.model_dump(mode="json"), b.id)])
    _stamped(a, b)
    check(main.hash_events([a, b]) != before,
          "grouping changes the day's hash, so the day re-solves")


def scenario_the_endpoints_run():
    import main
    _reset()
    main.trigger_background_refresh = lambda *a, **k: None
    a, b = pair()
    _cache(a, b)
    paths = {r.path for r in main.app.routes}
    check('/api/events/ride_group' in paths and '/api/events/{event_id}/ride_group' in paths,
          "both routes are mounted")
    res = main.ride_group_api({"event_ids": ["swim", "dive"]}, request=None)
    check(res.get("status") == "grouped" and len(storage.get_ride_group_rows()) == 2,
          f"POST groups the pair: {res} / {storage.get_ride_group_rows()}")
    try:
        main.ride_group_api({"event_ids": ["swim"]}, request=None)
        check(False, "one event is not a group")
    except HTTPException as e:
        check(e.status_code == 400, f"one event is refused: {e.status_code}")
    res = main.ride_ungroup_api("swim", {}, request=None)
    check(res.get("status") == "ungrouped" and storage.get_ride_group_rows() == [],
          f"DELETE ungroups, and the group of one dissolves: {storage.get_ride_group_rows()}")
    # A day outside the cached window: the page's own keys are enough.
    storage.cache_table.truncate()
    later = [e.model_dump(mode="json") for e in pair()]
    res = main.ride_group_api({"event_ids": ["swim", "dive"], "events": later}, request=None)
    check(res.get("status") == "grouped" and len(storage.get_ride_group_rows()) == 2,
          f"an uncached day groups from the page's keys: {storage.get_ride_group_rows()}")
    main.ride_ungroup_api("dive", {"event": later[1]}, request=None)
    check(storage.get_ride_group_rows() == [], "and ungroups the same way")
    try:
        main.ride_group_api({"event_ids": ["swim", "dive"]}, request=None)
        check(False, "uncached and no keys sent must be a 404")
    except HTTPException as e:
        check(e.status_code == 404, f"nothing to key by is a 404: {e.status_code}")
    storage.members_table.truncate()
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    try:
        main.ride_group_api({"event_ids": ["swim", "dive"], "member_id": "kid"}, request=None)
        check(False, "a child must not regroup the family's drives")
    except HTTPException as e:
        check(e.status_code == 403, f"a child is refused: {e.status_code}")
    storage.members_table.truncate()


def scenario_both_agent_stacks_group_by_name():
    import main
    from services import agent_tools_v2
    _reset()
    main.trigger_background_refresh = lambda *a, **k: None
    check({"group_events_ride_together", "ungroup_event"} <= set(agent_tools_v2.TOOL_HANDLERS)
          and {"group_events_ride_together", "ungroup_event"} <= set(agent_tools_v2.TOOL_SCHEMAS),
          "the v1 stack has schema and handler")
    v2_names = {t.get("name") for t in agent_tools_v2.get_available_tools()}
    check({"group_events_ride_together", "ungroup_event"} <= v2_names,
          "the chat widget's stack (agent_tools_v2) has them too")
    router_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'services', 'agent_router.py'), encoding='utf-8').read()
    check('"group_events_ride_together"' in router_src and 'ungroup_event(' in router_src,
          "and the router dispatches them")

    a, b = pair()
    _cache(a, b)
    day = DAY.date().isoformat()
    res = agent_tools_v2.TOOL_HANDLERS["group_events_ride_together"](
        {"event_names": ["swim", "dive"], "target_date": day})
    check(res.get("status") == "success" and len(storage.get_ride_group_rows()) == 2,
          f"v1 groups by name: {res} / {storage.get_ride_group_rows()}")
    res = agent_tools_v2.ungroup_event("dive", day)
    check(res.get("status") == "success" and storage.get_ride_group_rows() == [],
          f"v2 ungroups by name, and the pair dissolves: {res}")
    res = agent_tools_v2.group_events_ride_together("swim and dive", day)
    check(res.get("status") == "success" and len(storage.get_ride_group_rows()) == 2,
          f"a spoken list in one string is split, not refused: {res}")
    _reset()
    res = agent_tools_v2.group_events_ride_together(["swim", "swim"], day)
    check(res.get("status") == "error" and "both matched" in res.get("message", ""),
          f"two names for one event are refused out loud: {res}")
    res = agent_tools_v2.group_events_ride_together(["swim", "dive"], day,
                                                    acting_member={"id": "k", "role": "child"})
    check(res.get("status") == "error" and storage.get_ride_group_rows() == [],
          f"a child asking Argyle is refused: {res}")


def scenario_the_hand_path_exists():
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
    dash = open(os.path.join(tpl, 'dashboard.html'), encoding='utf-8').read()
    check("closest('[id^=\"event-\"]')" in dash and 'chooseDropAction' in dash
          and "'Group Events'" in dash and 'Assign to ${' in dash,
          "dropping on another event offers Group Events / Assign to <driver>")
    check("api/events/ride_group" in dash and 'leaveRideGroup' in dash,
          "grouping and ungrouping both have a hand path")
    check('reasonObj.ride_together' in dash and 'Ride together with' in dash,
          "the diagnostics panel offers the suggestion as a button")
    timeline = open(os.path.join(tpl, 'components', 'schedule_timeline.html'),
                    encoding='utf-8').read()
    check('ride-suggestion-section' in dash and 'edge.ride_together' in dash,
          "a late leg's offer reaches the event panel too")
    check('stRideGroupOf' in timeline and 'openRideGroupChip' in timeline,
          "grouped cards wear a chip that leads to ungroup")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} ride-group scenarios passed")
